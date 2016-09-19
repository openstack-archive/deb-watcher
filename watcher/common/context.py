# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_context import context
from oslo_log import log as logging
from oslo_utils import timeutils
import six

from watcher._i18n import _LW
from watcher.common import utils

LOG = logging.getLogger(__name__)


class RequestContext(context.RequestContext):
    """Extends security contexts from the OpenStack common library."""

    def __init__(self, user_id=None, project_id=None, is_admin=None,
                 roles=None, timestamp=None, request_id=None, auth_token=None,
                 auth_url=None, overwrite=True, user_name=None,
                 project_name=None, domain_name=None, domain_id=None,
                 auth_token_info=None, **kwargs):
        """Stores several additional request parameters:

        :param domain_id: The ID of the domain.
        :param domain_name: The name of the domain.
        :param is_public_api: Specifies whether the request should be processed
                              without authentication.

        """
        user = kwargs.pop('user', None)
        tenant = kwargs.pop('tenant', None)
        super(RequestContext, self).__init__(
            auth_token=auth_token,
            user=user_id or user,
            tenant=project_id or tenant,
            domain=kwargs.pop('domain', None) or domain_name or domain_id,
            user_domain=kwargs.pop('user_domain', None),
            project_domain=kwargs.pop('project_domain', None),
            is_admin=is_admin,
            read_only=kwargs.pop('read_only', False),
            show_deleted=kwargs.pop('show_deleted', False),
            request_id=request_id,
            resource_uuid=kwargs.pop('resource_uuid', None),
            is_admin_project=kwargs.pop('is_admin_project', True),
            overwrite=overwrite,
            roles=roles)

        self.remote_address = kwargs.pop('remote_address', None)
        self.instance_lock_checked = kwargs.pop('instance_lock_checked', None)
        self.read_deleted = kwargs.pop('read_deleted', None)
        self.service_catalog = kwargs.pop('service_catalog', None)
        self.quota_class = kwargs.pop('quota_class', None)

        # oslo_context's RequestContext.to_dict() generates this field, we can
        # safely ignore this as we don't use it.
        kwargs.pop('user_identity', None)
        if kwargs:
            LOG.warning(_LW('Arguments dropped when creating context: %s'),
                        str(kwargs))

        # FIXME(dims): user_id and project_id duplicate information that is
        # already present in the oslo_context's RequestContext. We need to
        # get rid of them.
        self.auth_url = auth_url
        self.domain_name = domain_name
        self.domain_id = domain_id
        self.auth_token_info = auth_token_info
        self.user_id = user_id
        self.project_id = project_id
        if not timestamp:
            timestamp = timeutils.utcnow()
        if isinstance(timestamp, six.string_types):
            timestamp = timeutils.parse_isotime(timestamp)
        self.timestamp = timestamp
        self.user_name = user_name
        self.project_name = project_name
        self.is_admin = is_admin
        # if self.is_admin is None:
        #     self.is_admin = policy.check_is_admin(self)

    def to_dict(self):
        values = super(RequestContext, self).to_dict()
        # FIXME(dims): defensive hasattr() checks need to be
        # removed once we figure out why we are seeing stack
        # traces
        values.update({
            'user_id': getattr(self, 'user_id', None),
            'user_name': getattr(self, 'user_name', None),
            'project_id': getattr(self, 'project_id', None),
            'project_name': getattr(self, 'project_name', None),
            'domain_id': getattr(self, 'domain_id', None),
            'domain_name': getattr(self, 'domain_name', None),
            'auth_token_info': getattr(self, 'auth_token_info', None),
            'is_admin': getattr(self, 'is_admin', None),
            'timestamp': utils.strtime(self.timestamp) if hasattr(
                self, 'timestamp') else None,
            'request_id': getattr(self, 'request_id', None),
        })
        return values

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    def __str__(self):
        return "<Context %s>" % self.to_dict()


def make_context(*args, **kwargs):
    return RequestContext(*args, **kwargs)
