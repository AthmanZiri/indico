# This file is part of Indico.
# Copyright (C) 2002 - 2015 European Organization for Nuclear Research (CERN).
#
# Indico is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.
#
# Indico is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Indico; if not, see <http://www.gnu.org/licenses/>.

from __future__ import unicode_literals

from collections import defaultdict

from flask import g
from sqlalchemy.event import listens_for
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import joinedload

from indico.core.db import db
from indico.core.db.sqlalchemy.links import LinkMixin
from indico.core.db.sqlalchemy.protection import ProtectionMixin, ProtectionMode
from indico.core.db.sqlalchemy.util.models import auto_table_args
from indico.modules.attachments.models.attachments import Attachment
from indico.modules.attachments.models.principals import AttachmentFolderPrincipal
from indico.util.decorators import strict_classproperty
from indico.util.string import return_ascii


class AttachmentFolder(LinkMixin, ProtectionMixin, db.Model):
    __tablename__ = 'folders'
    unique_links = 'is_default'

    @strict_classproperty
    @staticmethod
    def __auto_table_args():
        default_inheriting = 'not (is_default and protection_mode != {})'.format(ProtectionMode.inheriting.value)
        return (db.CheckConstraint(default_inheriting, 'default_inheriting'),
                db.CheckConstraint('is_default = (title IS NULL)', 'default_or_title'),
                db.CheckConstraint('not (is_default and is_deleted)', 'default_not_deleted'),
                {'schema': 'attachments'})

    @declared_attr
    def __table_args__(cls):
        return auto_table_args(cls)

    #: The ID of the folder
    id = db.Column(
        db.Integer,
        primary_key=True
    )
    #: The name of the folder (``None`` for the default folder)
    title = db.Column(
        db.String,
        nullable=True
    )
    #: The description of the folder
    description = db.Column(
        db.Text,
        nullable=False,
        default=''
    )
    #: If the folder has been deleted
    is_deleted = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    #: If the folder is the default folder (used for "folder-less" files)
    is_default = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    #: If the folder is always visible (even if you cannot access it)
    is_always_visible = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    _acl = db.relationship(
        'AttachmentFolderPrincipal',
        backref='folder',
        cascade='all, delete-orphan',
        collection_class=set
    )
    #: The ACL of the folder (used for ProtectionMode.protected)
    acl = association_proxy('_acl', 'principal', creator=lambda v: AttachmentFolderPrincipal(principal=v))

    #: The list of attachments that are not deleted, ordered by name
    attachments = db.relationship(
        'Attachment',
        primaryjoin=lambda: (Attachment.folder_id == AttachmentFolder.id) & ~Attachment.is_deleted,
        order_by=lambda: db.func.lower(Attachment.title),
        viewonly=True,
        lazy=True
    )

    # relationship backrefs:
    # - all_attachments (Attachment.folder)

    @property
    def protection_parent(self):
        return self.linked_object

    @classmethod
    def get_or_create_default(cls, linked_object):
        """Gets the default folder for the given object or creates it."""
        folder = cls.find_first(is_default=True, linked_object=linked_object)
        if folder is None:
            folder = cls(is_default=True, linked_object=linked_object)
        return folder

    @property
    def locator(self):
        return dict(self.linked_object.getLocator(), folder_id=self.id)

    def can_view(self, user):
        """Checks if the user can see the folder.

        This does not mean the user can actually access its contents.
        It just determines if it is visible to him or not.
        """
        return self.is_always_visible or super(AttachmentFolder, self).can_access(user)

    @classmethod
    def get_for_linked_object(cls, linked_object, preload_event=True):
        """Gets the attachments for the given object.

        This only returns attachments that haven't been deleted.

        :param linked_object: An event, session, contribution or
                              subcontribution.
        :param preload_event: If all attachments for the same event should
                              be pre-loaded and cached in the app context.
        """
        try:
            return g.event_attachments.get(linked_object)
        except AttributeError:
            if not preload_event:
                return (cls.find(linked_object=linked_object, is_deleted=False)
                           .order_by(AttachmentFolder.is_default.desc(), db.func.lower(AttachmentFolder.title))
                           .options(joinedload(AttachmentFolder.attachments))
                           .all())

            g.event_attachments = defaultdict(list)
            query = (cls.find(event_id=int(linked_object.getConference().id), is_deleted=False)
                        .order_by(AttachmentFolder.is_default.desc(), db.func.lower(AttachmentFolder.title))
                        .options(joinedload(AttachmentFolder.attachments)))

            # populate cache
            for obj in query:
                g.event_attachments[obj.linked_object].append(obj)

            return g.event_attachments.get(linked_object)

    @return_ascii
    def __repr__(self):
        return '<AttachmentFolder({}, {}{}{}{}, {}, {})>'.format(
            self.id,
            self.title,
            ', is_default=True' if self.is_default else '',
            ', is_always_visible=False' if not self.is_always_visible else '',
            ', is_deleted=True' if self.is_deleted else '',
            self.protection_repr,
            self.link_repr
        )


@listens_for(AttachmentFolder.attachments, 'append')
@listens_for(AttachmentFolder.attachments, 'remove')
def _wrong_attachments_modified(target, value, *unused):
    raise Exception('AttachmentFolder.attachments is view-only. Use all_attachments for write operations!')
