# 2016 by Deepak Kothandan
# 2020 extended by Nicolai Buchwitz

# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, division, print_function)

__metaclass__ = type

import json
import os
import uuid

from ansible import context
from ansible.module_utils._text import to_text
from ansible.module_utils.urls import open_url
from ansible.plugins.callback import CallbackBase

try:
    import prettytable

    HAS_PRETTYTABLE = True
except ImportError:
    HAS_PRETTYTABLE = False

DOCUMENTATION = '''
    callback: rocketchat
    callback_type: notification
    requirements:
      - whitelist in configuration
      - prettytable (python library)
    short_description: Sends play events to a Rocketchat channel
    description:
        - This is an ansible callback plugin that sends status updates to a Rocketchat channel during playbook execution.
    options:
      webhook_url:
        required: True
        description: Rocketchat Webhook URL
        env:
          - name: ROCKETCHAT_WEBHOOK_URL
        ini:
          - section: callback_rocketchat
            key: webhook_url
      channel:
        default: ""
        description: Rocketchat room to post in. The default (empty) will use the default configured in the webhook.
        env:
          - name: ROCKETCHAT_CHANNEL
        ini:
          - section: callback_rocketchat
            key: channel
      username:
        description: Username to post as.
        env:
          - name: ROCKETCHAT_USERNAME
        default: ansible
        ini:
          - section: callback_rocketchat
            key: username
      icon_url:
        description: Icon url for user avatar
        env:
          - name: ROCKETCHAT_ICON_URL
        default: ""
        ini:
          - section: callback_rocketchat
            key: icon_url
      icon_emoji:
        description: Icon emoji for user avatar
        env:
          - name: ROCKETCHAT_ICON_EMOJI
        default: ""
        ini:
          - section: callback_rocketchat
            key: icon_emoji
      validate_certs:
        description: validate the TLS certificate of the Rocketchat server. (For HTTPS URLs)
        env:
          - name: ROCKETCHAT_VALIDATE_CERTS
        ini:
          - section: callback_rocketchat
            key: validate_certs
        default: True
        type: bool
'''


class CallbackModule(CallbackBase):
    """This is an ansible callback plugin that sends status
    updates to a Rocketchat channel during playbook execution.
    """
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'rocket'
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self, display=None):

        super(CallbackModule, self).__init__(display=display)

        if not HAS_PRETTYTABLE:
            self.disabled = True
            self._display.warning('The `prettytable` python module is not '
                                  'installed. Disabling the RocketChat callback '
                                  'plugin.')

        self.playbook_name = None

        # This is a 6 character identifier provided with each message
        # This makes it easier to correlate messages when there are more
        # than 1 simultaneous playbooks running
        self.guid = uuid.uuid4().hex[:6]

    def set_options(self, task_keys=None, var_options=None, direct=None):

        super(CallbackModule, self).set_options(task_keys=task_keys, var_options=var_options, direct=direct)

        self.webhook_url = self.get_option('webhook_url')
        self.channel = self.get_option('channel')
        self.username = self.get_option('username')
        self.show_invocation = (self._display.verbosity > 1)
        self.validate_certs = self.get_option('validate_certs')
        self.icon_emoji = self.get_option('icon_emoji')
        self.icon_url = self.get_option('icon_url')

        if self.webhook_url is None:
            self.disabled = True
            self._display.warning('Slack Webhook URL was not provided. The '
                                  'Slack Webhook URL can be provided using '
                                  'the `SLACK_WEBHOOK_URL` environment '
                                  'variable.')

    def send_msg(self, attachments):
        headers = {
            'Content-type': 'application/json',
        }

        payload = {
            'username': self.username,
            'channel': self.channel,
            'icon_url': self.icon_url,
            'icon_emoji': self.icon_emoji,
            'attachments': attachments,
            'parse': 'none',
        }

        data = json.dumps(payload)
        self._display.debug(data)
        self._display.debug(self.webhook_url)
        try:
            response = open_url(self.webhook_url, data=data, headers=headers)
            return response.read()
        except Exception as e:
            self._display.warning('Could not submit message to RocketChat: %s' %
                                  str(e))

    def v2_playbook_on_start(self, playbook):
        self.playbook_name = os.path.basename(playbook._file_name)

        title = [
            '*Playbook initiated* (_%s_)' % self.guid
        ]

        invocation_items = []
        if context.CLIARGS and self.show_invocation:
            tags = context.CLIARGS['tags']
            skip_tags = context.CLIARGS['skip_tags']
            extra_vars = context.CLIARGS['extra_vars']
            subset = context.CLIARGS['subset']
            inventory = [os.path.abspath(i) for i in context.CLIARGS['inventory']]

            invocation_items.append('Inventory:  %s' % ', '.join(inventory))
            if tags and tags != ['all']:
                invocation_items.append('Tags:       %s' % ', '.join(tags))
            if skip_tags:
                invocation_items.append('Skip Tags:  %s' % ', '.join(skip_tags))
            if subset:
                invocation_items.append('Limit:      %s' % subset)
            if extra_vars:
                invocation_items.append('Extra Vars: %s' %
                                        ' '.join(extra_vars))

            title.append('by *%s*' % context.CLIARGS['remote_user'])

        title.append('\n\n*%s*' % self.playbook_name)
        msg_items = [' '.join(title)]
        if invocation_items:
            msg_items.append('```\n%s\n```' % '\n'.join(invocation_items))

        msg = '\n'.join(msg_items)

        attachments = [{
            'fallback': msg,
            'fields': [
                {
                    'value': msg
                }
            ],
            'color': 'warning',
            'mrkdwn_in': ['text', 'fallback', 'fields'],
        }]

        self.send_msg(attachments=attachments)

    def v2_playbook_on_play_start(self, play):
        """Display Play start messages"""

        name = play.name or 'Play name not specified (%s)' % play._uuid
        msg = '*Starting play* (_%s_)\n\n*%s*' % (self.guid, name)
        attachments = [
            {
                'fallback': msg,
                'text': msg,
                'color': 'warning',
                'mrkdwn_in': ['text', 'fallback', 'fields'],
            }
        ]
        self.send_msg(attachments=attachments)

    def v2_playbook_on_stats(self, stats):
        """Display info about playbook statistics"""

        hosts = sorted(stats.processed.keys())

        t = prettytable.PrettyTable(['Host', 'Ok', 'Changed', 'Unreachable',
                                     'Failures', 'Rescued', 'Ignored'])

        failures = False
        unreachable = False

        for h in hosts:
            s = stats.summarize(h)

            if s['failures'] > 0:
                failures = True
            if s['unreachable'] > 0:
                unreachable = True

            t.add_row([h] + [s[k] for k in ['ok', 'changed', 'unreachable',
                                            'failures', 'rescued', 'ignored']])

        attachments = []
        msg_items = [
            '*Playbook Complete* (_%s_)' % self.guid
        ]
        if failures or unreachable:
            color = 'danger'
            msg_items.append('\n*Failed!*')
        else:
            color = 'good'
            msg_items.append('\n*Success!*')

        msg_items.append('```\n%s\n```' % t)

        msg = '\n'.join(msg_items)

        attachments.append({
            'fallback': msg,
            'fields': [
                {
                    'value': msg
                }
            ],
            'color': color,
            'mrkdwn_in': ['text', 'fallback', 'fields']
        })

        self.send_msg(attachments=attachments)
