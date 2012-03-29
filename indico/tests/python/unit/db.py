# -*- coding: utf-8 -*-
##
##
## This file is part of CDS Indico.
## Copyright (C) 2002, 2003, 2004, 2005, 2006, 2007 CERN.
##
## CDS Indico is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 2 of the
## License, or (at your option) any later version.
##
## CDS Indico is distributed in the hope that it will be useful, but
## WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
## General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with CDS Indico; if not, write to the Free Software Foundation, Inc.,
## 59 Temple Place, Suite 330, Boston, MA 02111-1307, USA.

# ZODB imports
import ZODB
from ZODB import ConflictResolution, MappingStorage
import transaction
from ZODB.POSException import ConflictError

# legacy imports
from MaKaC.common.db import DBMgr


# indico imports
from indico.tests.python.unit.util import IndicoTestFeature
from indico.tests import default_actions


class TestMemStorage(MappingStorage.MappingStorage,
                     ConflictResolution.ConflictResolvingStorage):

    """
    Test memory storage - useful for conflicts
    """

    def __init__(self, name='foo'):
        MappingStorage.MappingStorage.__init__(self, name)
        ConflictResolution.ConflictResolvingStorage.__init__(self)

    @ZODB.utils.locked(MappingStorage.MappingStorage.opened)
    def store(self, oid, serial, data, version, transaction):
        assert not version, "Versions are not supported"
        if transaction is not self._transaction:
            raise ZODB.POSException.StorageTransactionError(self, transaction)

        old_tid = None
        tid_data = self._data.get(oid)
        if tid_data:
            old_tid = tid_data.maxKey()
            if serial != old_tid:
                data = self.tryToResolveConflict(oid, old_tid, serial, data)

        self._tdata[oid] = data

        return self._tid


class Database_Feature(IndicoTestFeature):
    """
    Connects/disconnects the database
    """

    _requires = []

    def start(self, obj):
        super(Database_Feature, self).start(obj)

        obj._dbmgr = DBMgr.getInstance()

        retries = 10
        # quite prone to DB conflicts
        while retries:
            try:
                with obj._context('database', sync=True) as conn:
                    obj._home = default_actions.initialize_new_db(conn.root())
                break
            except ConflictError:
                retries -= 1

    def _action_startDBReq(obj):
        obj._dbmgr.startRequest()
        obj._conn = obj._dbmgr.getDBConnection()
        return obj._conn

    def _action_stopDBReq(obj):
        transaction.commit()
        obj._conn.close()
        obj._conn = None

    def _context_database(self, sync=False):
        conn = self._startDBReq()
        if sync:
            conn.sync()
        try:
            yield conn
        finally:
            self._stopDBReq()

    def destroy(self, obj):
        obj._conn = None


class DummyUser_Feature(IndicoTestFeature):

    """
    Creates a dummy user - needs database
    """

    _requires = ['db.Database']

    def start(self, obj):
        super(DummyUser_Feature, self).start(obj)

        with obj._context('database', sync=True):
            obj._dummy = default_actions.create_dummy_user()
