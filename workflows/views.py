# -*- coding: utf-8 -*-
from cms.models import Page, Title
from cms.utils.urlutils import admin_reverse
from django.contrib import messages
from django.http import Http404
from django.shortcuts import render, redirect
from django.utils.translation import ugettext_lazy as _
from django.core.urlresolvers import reverse

# Create your views here.
# TODO Views handling action creation
from django.utils.functional import cached_property
from django.views.generic.edit import FormView

from workflows.forms import ActionForm
from workflows.models import Action
from workflows.utils import get_current_request
from workflows.utils.email import send_action_mails
from workflows.utils.workflow import get_workflow


NO_WORKFLOW = _('')  # TODO
ACTIVE_REQUEST = _('')
NO_ACTIVE_REQUEST = _('')
USER_NOT_ALLOWED = _('')

CLOSE_FRAME = 'admin/cms/page/close_frame.html'


class ActionView(FormView):
    form_class = ActionForm
    action_type = None
    admin_title = None
    admin_save_label = None

    # def dispatch(self, request, *args, **kwargs):
    #     return super(ActionView, self).dispatch(request, *args, **kwargs)

    @cached_property
    def language(self):
        """
        :rtype: str
        """
        return self.args[1]

    @cached_property
    def page(self):
        """
        :rtype: Page
        """
        pk = self.args[0]
        try:
            return Page.objects.get(
                pk=pk,
                publisher_is_draft=True,  # redundant, but ensuring we only deal with drafts
            )
        except Page.DoesNotExist:
            raise Http404

    @cached_property
    def title(self):
        """
        :rtype: Title
        """
        try:
            return self.page.title_set.get(language=self.language)
        except Title.DoesNotExist:
            raise Http404

    @cached_property
    def workflow(self):
        """
        :rtype: workflows.models.Workflow
        """
        return get_workflow(self.title)

    @cached_property
    def user(self):
        """
        :rtype: django.contrib.auth.models.User
        """
        return self.request.user

    @cached_property
    def action_request(self):
        """
        :rtype: Action
        """
        return get_current_request(self.title)

    @cached_property
    def stage(self):
        """
        :rtype: workflows.models.WorkflowStage
        """
        if not self.action_request:
            return None
        return self.action_request.get_next_stage(self.user)

    def validate(self):
        if self.workflow is None:
            raise InvalidAction(NO_WORKFLOW)

    def get_success_url(self):
        return self.title.path

    def get_failed_url(self):
        return self.request.META.get('HTTP_REFERER', self.get_success_url())

    def get_form_url(self):
        return self.request.path

    def dispatch(self, request, *args, **kwargs):
        try:
            self.validate()
        except InvalidAction as e:
            messages.error(request, e.message)
            return redirect(self.get_failed_url())
        return super(ActionView, self).dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super(ActionView, self).get_form_kwargs()
        kwargs.update({
            'title': self.title,
            'stage': self.stage,
            'workflow': self.workflow,
            'action_type': self.action_type,
            'request': self.request,
        })
        return kwargs

    def form_valid(self, form):
        action = form.save()
        send_action_mails(action, editor=form.editor)
        messages.success(self.request, self.success_message)
        # context = self.get_context_data(form=form)
        return render(self.request, CLOSE_FRAME, {})

    def get_context_data(self, **kwargs):
        ctx = super(ActionView, self).get_context_data(**kwargs)
        form = ctx.get('form')
        # Admin context
        ctx.update({
            # 'title': self.admin_title,
            'has_change_permission': True,
            'opts': Action._meta,
            'root_path': reverse('admin:index'),
            'adminform': ctx.get('form'),
            'errors': form.errors,
            'is_popup': True,
            'form_url': self.get_form_url(),
            'save_label': self.admin_save_label
        })
        return ctx


class RequestView(ActionView):
    action_type = Action.REQUEST
    admin_title = _('Submit request for changes')
    admin_save_label = _('Submit request for changes')

    def validate(self):
        super(RequestView, self).validate()
        if self.action_request and not self.action_request.is_closed():
            raise InvalidAction(ACTIVE_REQUEST)


class ApproveRejectMixinView(object):
    def validate(self):
        super(ApproveRejectMixinView, self).validate()
        if self.action_request is None:
            raise InvalidAction(NO_ACTIVE_REQUEST)
        if self.stage is None:
            raise InvalidAction(USER_NOT_ALLOWED)


class ApproveView(ApproveRejectMixinView, ActionView):
    action_type = Action.APPROVE
    admin_title = _('Approve request')
    admin_save_label = admin_title


class RejectView(ApproveRejectMixinView, ActionView):
    action_type = Action.REJECT
    admin_title = _('Reject request')
    admin_save_label = admin_title


class CancelView(ActionView):
    action_type = Action.CANCEL
    admin_title = _('Cancel request')
    admin_save_label = admin_title


WORKFLOW_VIEWS = {
    Action.REQUEST: RequestView,
    Action.APPROVE: ApproveView,
    Action.REJECT: RejectView,
    Action.CANCEL: CancelView,
}


class InvalidAction(Exception):
    def __init__(self, message):
        self.message = message
        super(InvalidAction, self).__init__()
