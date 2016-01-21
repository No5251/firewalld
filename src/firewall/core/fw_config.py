# -*- coding: utf-8 -*-
#
# Copyright (C) 2011-2012 Red Hat, Inc.
#
# Authors:
# Thomas Woerner <twoerner@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import copy
import os, os.path
from firewall.config import *
from firewall.core.base import *
from firewall.core.logger import log
from firewall.core.io.icmptype import IcmpType, icmptype_reader, icmptype_writer
from firewall.core.io.service import Service, service_reader, service_writer
from firewall.core.io.zone import Zone, zone_reader, zone_writer
from firewall.core.io.ipset import IPSet, ipset_reader, ipset_writer
from firewall.functions import portStr
from firewall.errors import *

class FirewallConfig(object):
    def __init__(self, fw):
        self._fw = fw
        self.__init_vars()

    def __repr__(self):
        return '%s(%r, %r, %r, %r, %r, %r, %r, %r, %r, %r, %r)' % (self.__class__,
                   self._ipsets, self._icmptypes, self._services, self._zones,
                   self._builtin_ipsets, self._builtin_icmptypes, self._builtin_services, self._builtin_zones,
                   self._firewalld_conf, self._policies, self._direct)

    def __init_vars(self):
        self._ipsets = { }
        self._icmptypes = { }
        self._services = { }
        self._zones = { }
        self._builtin_ipsets = { }
        self._builtin_icmptypes = { }
        self._builtin_services = { }
        self._builtin_zones = { }
        self._firewalld_conf = None
        self._policies = None
        self._direct = None

    def cleanup(self):
        for x in list(self._builtin_ipsets.keys()):
            self._builtin_ipsets[x].cleanup()
            del self._builtin_ipsets[x]
        for x in list(self._ipsets.keys()):
            self._ipsets[x].cleanup()
            del self._ipsets[x]

        for x in list(self._builtin_icmptypes.keys()):
            self._builtin_icmptypes[x].cleanup()
            del self._builtin_icmptypes[x]
        for x in list(self._icmptypes.keys()):
            self._icmptypes[x].cleanup()
            del self._icmptypes[x]

        for x in list(self._builtin_services.keys()):
            self._builtin_services[x].cleanup()
            del self._builtin_services[x]
        for x in list(self._services.keys()):
            self._services[x].cleanup()
            del self._services[x]

        for x in list(self._builtin_zones.keys()):
            self._builtin_zones[x].cleanup()
            del self._builtin_zones[x]
        for x in list(self._zones.keys()):
            self._zones[x].cleanup()
            del self._zones[x]

        if self._firewalld_conf:
            self._firewalld_conf.cleanup()
            del self._firewalld_conf
            self._firewalld_conf = None

        if self._policies:
            self._policies.cleanup()
            del self._policies
            self._policies = None

        if self._direct:
            self._direct.cleanup()
            del self._direct
            self._direct = None

        self.__init_vars()

    # access check

    def lockdown_enabled(self):
        return self._fw.policies.query_lockdown()

    def access_check(self, key, value):
        return self._fw.policies.access_check(key, value)

    # firewalld_conf

    def set_firewalld_conf(self, conf):
        self._firewalld_conf = conf

    def get_firewalld_conf(self):
        return self._firewalld_conf

    def update_firewalld_conf(self):
        if not os.path.exists(FIREWALLD_CONF):
            self._firewalld_conf.clear()
        else:
            self._firewalld_conf.read()

    # policies

    def set_policies(self, policies):
        self._policies = policies

    def get_policies(self):
        return self._policies

    def update_lockdown_whitelist(self):
        if not os.path.exists(LOCKDOWN_WHITELIST):
            self._policies.lockdown_whitelist.cleanup()
        else:
            self._policies.lockdown_whitelist.read()

    # direct

    def set_direct(self, direct):
        self._direct = direct

    def get_direct(self):
        return self._direct

    def update_direct(self):
        if not os.path.exists(FIREWALLD_DIRECT):
            self._direct.cleanup()
        else:
            self._direct.read()

    # ipset

    def get_ipsets(self):
        return sorted(set(list(self._ipsets.keys()) + \
                          list(self._builtin_ipsets.keys())))

    def add_ipset(self, obj):
        if obj.builtin:
            self._builtin_ipsets[obj.name] = obj
        else:
            self._ipsets[obj.name] = obj

    def get_ipset(self, name):
        if name in self._ipsets:
            return self._ipsets[name]
        elif name in self._builtin_ipsets:
            return self._builtin_ipsets[name]
        raise FirewallError(INVALID_IPSET, name)

    def load_ipset_defaults(self, obj):
        if obj.name not in self._ipsets:
            raise FirewallError(NO_DEFAULTS,
                                "'%s' not in self._ipsets" % obj.name)
        elif self._ipsets[obj.name] != obj:
            raise FirewallError(NO_DEFAULTS,
                                "self._ipsets[%s] != obj" % obj.name)
        elif obj.name not in self._builtin_ipsets:
            raise FirewallError(NO_DEFAULTS,
                            "'%s' not in self._builtin_ipsets" % obj.name)
        self._remove_ipset(obj)
        return self._builtin_ipsets[obj.name]

    def get_ipset_config(self, obj):
        return obj.export_config()

    def set_ipset_config(self, obj, config):
        if obj.builtin:
            x = copy.copy(obj)
            x.import_config(config)
            x.path = ETC_FIREWALLD_IPSETS
            if obj.path != x.path:
                x.default = False
            self.add_ipset(x)
            ipset_writer(x)
            return x
        else:
            obj.import_config(config)
            ipset_writer(obj)
            return obj

    def new_ipset(self, name, config):
        try:
            self.get_ipset(name)
        except:
            pass
        else:
            raise FirewallError(NAME_CONFLICT, "new_ipset(): '%s'" % name)

        x = IPSet()
        x.check_name(name)
        x.import_config(config)
        x.name = name
        x.filename = "%s.xml" % name
        x.path = ETC_FIREWALLD_IPSETS
        # It is not possible to add a new one with a name of a buitin
        x.default = True

        ipset_writer(x)
        self.add_ipset(x)
        return x

    def update_ipset_from_path(self, name):
        filename = os.path.basename(name)
        path = os.path.dirname(name)

        if not os.path.exists(name):
            # removed file

            if path == ETC_FIREWALLD_IPSETS:
                # removed custom ipset
                for x in self._ipsets.keys():
                    obj = self._ipsets[x]
                    if obj.filename == filename:
                        del self._ipsets[x]
                        if obj.name in self._builtin_ipsets:
                            return ("update", self._builtin_ipsets[obj.name])
                        return ("remove", obj)
            else:
                # removed builtin ipset
                for x in self._builtin_ipsets.keys():
                    obj = self._builtin_ipsets[x]
                    if obj.filename == filename:
                        del self._builtin_ipsets[x]
                        if obj.name not in self._ipsets:
                            # update dbus ipset
                            return ("remove", obj)
                        else:
                            # builtin hidden, no update needed
                            return (None, None)

            # ipset not known to firewalld, yet (timeout, ..)
            return (None, None)

        # new or updated file

        log.debug1("Loading ipset file '%s'", filename)
        try:
            obj = ipset_reader(filename, path)
        except Exception as msg:
            log.error("Failed to load ipset file '%s': %s", filename, msg)
            return (None, None)

        # new ipset
        if obj.name not in self._builtin_ipsets and obj.name not in self._ipsets:
            self.add_ipset(obj)
            return ("new", obj)

        # updated ipset
        if path == ETC_FIREWALLD_IPSETS:
            # custom ipset update
            if obj.name in self._ipsets:
                self._ipsets[obj.name] = obj
            return ("update", obj)
        else:
            if obj.name in self._builtin_ipsets:
                # builtin ipset update
                del self._builtin_ipsets[obj.name]
                self._builtin_ipsets[obj.name] = obj

                if obj.name not in self._ipsets:
                    # update dbus ipset
                    return ("update", obj)
                else:
                    # builtin hidden, no update needed
                    return (None, None)

        # ipset not known to firewalld, yet (timeout, ..)
        return (None, None)

    def _remove_ipset(self, obj):
        if obj.name not in self._ipsets:
            raise FirewallError(INVALID_IPSET,
                                "'%s' not in self._ipsets" % obj.name)
        if obj.path != ETC_FIREWALLD_IPSETS:
            raise FirewallError(INVALID_DIRECTORY,
                        "'%s' != '%s'" % (obj.path, ETC_FIREWALLD_IPSETS))
        os.remove("%s/%s.xml" % (obj.path, obj.name))
        del self._ipsets[obj.name]

    def check_builtin_ipset(self, obj):
        if obj.builtin:
            raise FirewallError(BUILTIN_IPSET,
                                "'%s' is built-in icmp type" % obj.name)

    def remove_ipset(self, obj):
        self.check_builtin_ipset(obj)
        self._remove_ipset(obj)

    def rename_ipset(self, obj, name):
        self.check_builtin_ipset(obj)
        new_ipset = self._copy_ipset(obj, name)
        self._remove_ipset(obj)
        return new_ipset

    def _copy_ipset(self, obj, name):
        return self.new_ipset(name, obj.export_config())

    # icmptypes

    def get_icmptypes(self):
        return sorted(set(list(self._icmptypes.keys()) + \
                          list(self._builtin_icmptypes.keys())))

    def add_icmptype(self, obj):
        if obj.builtin:
            self._builtin_icmptypes[obj.name] = obj
        else:
            self._icmptypes[obj.name] = obj

    def get_icmptype(self, name):
        if name in self._icmptypes:
            return self._icmptypes[name]
        elif name in self._builtin_icmptypes:
            return self._builtin_icmptypes[name]
        raise FirewallError(INVALID_ICMPTYPE, name)

    def load_icmptype_defaults(self, obj):
        if obj.name not in self._icmptypes:
            raise FirewallError(NO_DEFAULTS,
                                "'%s' not in self._icmptypes" % obj.name)
        elif self._icmptypes[obj.name] != obj:
            raise FirewallError(NO_DEFAULTS,
                                "self._icmptypes[%s] != obj" % obj.name)
        elif obj.name not in self._builtin_icmptypes:
            raise FirewallError(NO_DEFAULTS,
                            "'%s' not in self._builtin_icmptypes" % obj.name)
        self._remove_icmptype(obj)
        return self._builtin_icmptypes[obj.name]

    def get_icmptype_config(self, obj):
        return obj.export_config()

    def set_icmptype_config(self, obj, config):
        if obj.builtin:
            x = copy.copy(obj)
            x.import_config(config)
            x.path = ETC_FIREWALLD_ICMPTYPES
            if obj.path != x.path:
                x.default = False
            self.add_icmptype(x)
            icmptype_writer(x)
            return x
        else:
            obj.import_config(config)
            icmptype_writer(obj)
            return obj

    def new_icmptype(self, name, config):
        try:
            self.get_icmptype(name)
        except:
            pass
        else:
            raise FirewallError(NAME_CONFLICT, "new_icmptype(): '%s'" % name)

        x = IcmpType()
        x.check_name(name)
        x.import_config(config)
        x.name = name
        x.filename = "%s.xml" % name
        x.path = ETC_FIREWALLD_ICMPTYPES
        # It is not possible to add a new one with a name of a buitin
        x.default = True

        icmptype_writer(x)
        self.add_icmptype(x)
        return x

    def update_icmptype_from_path(self, name):
        filename = os.path.basename(name)
        path = os.path.dirname(name)

        if not os.path.exists(name):
            # removed file

            if path == ETC_FIREWALLD_ICMPTYPES:
                # removed custom icmptype
                for x in self._icmptypes.keys():
                    obj = self._icmptypes[x]
                    if obj.filename == filename:
                        del self._icmptypes[x]
                        if obj.name in self._builtin_icmptypes:
                            return ("update", self._builtin_icmptypes[obj.name])
                        return ("remove", obj)
            else:
                # removed builtin icmptype
                for x in self._builtin_icmptypes.keys():
                    obj = self._builtin_icmptypes[x]
                    if obj.filename == filename:
                        del self._builtin_icmptypes[x]
                        if obj.name not in self._icmptypes:
                            # update dbus icmptype
                            return ("remove", obj)
                        else:
                            # builtin hidden, no update needed
                            return (None, None)

            # icmptype not known to firewalld, yet (timeout, ..)
            return (None, None)

        # new or updated file

        log.debug1("Loading icmptype file '%s'", filename)
        try:
            obj = icmptype_reader(filename, path)
        except Exception as msg:
            log.error("Failed to load icmptype file '%s': %s", filename, msg)
            return (None, None)

        # new icmptype
        if obj.name not in self._builtin_icmptypes and obj.name not in self._icmptypes:
            self.add_icmptype(obj)
            return ("new", obj)

        # updated icmptype
        if path == ETC_FIREWALLD_ICMPTYPES:
            # custom icmptype update
            if obj.name in self._icmptypes:
                self._icmptypes[obj.name] = obj
            return ("update", obj)
        else:
            if obj.name in self._builtin_icmptypes:
                # builtin icmptype update
                del self._builtin_icmptypes[obj.name]
                self._builtin_icmptypes[obj.name] = obj

                if obj.name not in self._icmptypes:
                    # update dbus icmptype
                    return ("update", obj)
                else:
                    # builtin hidden, no update needed
                    return (None, None)
            
        # icmptype not known to firewalld, yet (timeout, ..)
        return (None, None)

    def _remove_icmptype(self, obj):
        if obj.name not in self._icmptypes:
            raise FirewallError(INVALID_ICMPTYPE,
                                "'%s' not in self._icmptypes" % obj.name)
        if obj.path != ETC_FIREWALLD_ICMPTYPES:
            raise FirewallError(INVALID_DIRECTORY,
                        "'%s' != '%s'" % (obj.path, ETC_FIREWALLD_ICMPTYPES))
        os.remove("%s/%s.xml" % (obj.path, obj.name))
        del self._icmptypes[obj.name]

    def check_builtin_icmptype(self, obj):
        if obj.builtin:
            raise FirewallError(BUILTIN_ICMPTYPE,
                                "'%s' is built-in icmp type" % obj.name)

    def remove_icmptype(self, obj):
        self.check_builtin_icmptype(obj)
        self._remove_icmptype(obj)

    def rename_icmptype(self, obj, name):
        self.check_builtin_icmptype(obj)
        new_icmptype = self._copy_icmptype(obj, name)
        self._remove_icmptype(obj)
        return new_icmptype

    def _copy_icmptype(self, obj, name):
        return self.new_icmptype(name, obj.export_config())

    # services

    def get_services(self):
        return sorted(set(list(self._services.keys()) + \
                          list(self._builtin_services.keys())))

    def add_service(self, obj):
        if obj.builtin:
            self._builtin_services[obj.name] = obj
        else:
            self._services[obj.name] = obj

    def get_service(self, name):
        if name in self._services:
            return self._services[name]
        elif name in self._builtin_services:
            return self._builtin_services[name]
        raise FirewallError(INVALID_SERVICE, "get_service(): '%s'" % name)

    def load_service_defaults(self, obj):
        if obj.name not in self._services:
            raise FirewallError(NO_DEFAULTS,
                                "'%s' not in self._services" % obj.name)
        elif self._services[obj.name] != obj:
            raise FirewallError(NO_DEFAULTS,
                                "self._services[%s] != obj" % obj.name)
        elif obj.name not in self._builtin_services:
            raise FirewallError(NO_DEFAULTS,
                            "'%s' not in self._builtin_services" % obj.name)
        self._remove_service(obj)
        return self._builtin_services[obj.name]

    def get_service_config(self, obj):
        return obj.export_config()

    def set_service_config(self, obj, config):
        if obj.builtin:
            x = copy.copy(obj)
            x.import_config(config)
            x.path = ETC_FIREWALLD_SERVICES
            if obj.path != x.path:
                x.default = False
            self.add_service(x)
            service_writer(x)
            return x
        else:
            obj.import_config(config)
            service_writer(obj)
            return obj

    def new_service(self, name, config):
        try:
            self.get_service(name)
        except:
            pass
        else:
            raise FirewallError(NAME_CONFLICT, "new_service(): '%s'" % name)

        x = Service()
        x.check_name(name)
        x.import_config(config)
        x.name = name
        x.filename = "%s.xml" % name
        x.path = ETC_FIREWALLD_SERVICES
        # It is not possible to add a new one with a name of a buitin
        x.default = True

        service_writer(x)
        self.add_service(x)
        return x

    def update_service_from_path(self, name):
        filename = os.path.basename(name)
        path = os.path.dirname(name)

        if not os.path.exists(name):
            # removed file

            if path == ETC_FIREWALLD_SERVICES:
                # removed custom service
                for x in self._services.keys():
                    obj = self._services[x]
                    if obj.filename == filename:
                        del self._services[x]
                        if obj.name in self._builtin_services:
                            return ("update", self._builtin_services[obj.name])
                        return ("remove", obj)
            else:
                # removed builtin service
                for x in self._builtin_services.keys():
                    obj = self._builtin_services[x]
                    if obj.filename == filename:
                        del self._builtin_services[x]
                        if obj.name not in self._services:
                            # update dbus service
                            return ("remove", obj)
                        else:
                            # builtin hidden, no update needed
                            return (None, None)

            # service not known to firewalld, yet (timeout, ..)
            return (None, None)

        # new or updated file

        log.debug1("Loading service file '%s'", filename)
        try:
            obj = service_reader(filename, path)
        except Exception as msg:
            log.error("Failed to load service file '%s': %s", filename, msg)
            return (None, None)

        # new service
        if obj.name not in self._builtin_services and obj.name not in self._services:
            self.add_service(obj)
            return ("new", obj)

        # updated service
        if path == ETC_FIREWALLD_SERVICES:
            # custom service update
            if obj.name in self._services:
                self._services[obj.name] = obj
            return ("update", obj)
        else:
            if obj.name in self._builtin_services:
                # builtin service update
                del self._builtin_services[obj.name]
                self._builtin_services[obj.name] = obj

                if obj.name not in self._services:
                    # update dbus service
                    return ("update", obj)
                else:
                    # builtin hidden, no update needed
                    return (None, None)
            
        # service not known to firewalld, yet (timeout, ..)
        return (None, None)

    def _remove_service(self, obj):
        if obj.name not in self._services:
            raise FirewallError(INVALID_SERVICE,
                                "'%s' not in self._services" % obj.name)
        if obj.path != ETC_FIREWALLD_SERVICES:
            raise FirewallError(INVALID_DIRECTORY,
                        "'%s' != '%s'" % (obj.path, ETC_FIREWALLD_SERVICES))
        os.remove("%s/%s.xml" % (obj.path, obj.name))
        del self._services[obj.name]

    def check_builtin_service(self, obj):
        if obj.builtin:
            raise FirewallError(BUILTIN_SERVICE,
                                "'%s' is built-in service" % obj.name)

    def remove_service(self, obj):
        self.check_builtin_service(obj)
        self._remove_service(obj)

    def rename_service(self, obj, name):
        self.check_builtin_service(obj)
        new_service = self._copy_service(obj, name)
        self._remove_service(obj)
        return new_service

    def _copy_service(self, obj, name):
        return self.new_service(name, obj.export_config())

    # zones

    def get_zones(self):
        return sorted(set(list(self._zones.keys()) + \
                          list(self._builtin_zones.keys())))

    def add_zone(self, obj):
        if obj.builtin:
            self._builtin_zones[obj.name] = obj
        else:
            self._zones[obj.name] = obj

    def forget_zone(self, name):
        if name in self._builtin_zones:
            del self._builtin_zones[name]
        if name in self._zones:
            del self._zones[name]

    def get_zone(self, name):
        if name in self._zones:
            return self._zones[name]
        elif name in self._builtin_zones:
            return self._builtin_zones[name]
        raise FirewallError(INVALID_ZONE, "get_zone(): %s" % name)

    def load_zone_defaults(self, obj):
        if obj.name not in self._zones:
            raise FirewallError(NO_DEFAULTS,
                                "'%s' not in self._zones" % obj.name)
        elif self._zones[obj.name] != obj:
            raise FirewallError(NO_DEFAULTS,
                                "self._zones[%s] != obj" % obj.name)
        elif obj.name not in self._builtin_zones:
            raise FirewallError(NO_DEFAULTS,
                                "'%s' not in self._builtin_zones" % obj.name)
        self._remove_zone(obj)
        return self._builtin_zones[obj.name]

    def get_zone_config(self, obj):
        return obj.export_config()

    def set_zone_config(self, obj, config):
        if obj.builtin:
            x = copy.copy(obj)
            x.fw_config = self
            x.import_config(config)
            x.path = ETC_FIREWALLD_ZONES
            if obj.path != x.path:
                x.default = False
            self.add_zone(x)
            zone_writer(x)
            return x
        else:
            obj.fw_config = self
            obj.import_config(config)
            zone_writer(obj)
            return obj

    def new_zone(self, name, config):
        try:
            self.get_zone(name)
        except:
            pass
        else:
            raise FirewallError(NAME_CONFLICT, "new_zone(): '%s'" % name)

        x = Zone()
        x.check_name(name)
        x.fw_config = self
        x.import_config(config)
        x.name = name
        x.filename = "%s.xml" % name
        x.path = ETC_FIREWALLD_ZONES
        # It is not possible to add a new one with a name of a buitin
        x.default = True

        zone_writer(x)
        self.add_zone(x)
        return x

    def update_zone_from_path(self, name):
        filename = os.path.basename(name)
        path = os.path.dirname(name)

        if not os.path.exists(name):
            # removed file

            if path == ETC_FIREWALLD_ZONES:
                # removed custom zone
                for x in self._zones.keys():
                    obj = self._zones[x]
                    if obj.filename == filename:
                        del self._zones[x]
                        if obj.name in self._builtin_zones:
                            return ("update", self._builtin_zones[obj.name])
                        return ("remove", obj)
            else:
                # removed builtin zone
                for x in self._builtin_zones.keys():
                    obj = self._builtin_zones[x]
                    if obj.filename == filename:
                        del self._builtin_zones[x]
                        if obj.name not in self._zones:
                            # update dbus zone
                            return ("remove", obj)
                        else:
                            # builtin hidden, no update needed
                            return (None, None)

            # zone not known to firewalld, yet (timeout, ..)
            return (None, None)

        # new or updated file

        log.debug1("Loading zone file '%s'", filename)
        try:
            obj = zone_reader(filename, path)
        except Exception as msg:
            log.error("Failed to load zone file '%s': %s", filename, msg)
            return (None, None)

        obj.fw_config = self

        # new zone
        if obj.name not in self._builtin_zones and obj.name not in self._zones:
            self.add_zone(obj)
            return ("new", obj)

        # updated zone
        if path == ETC_FIREWALLD_ZONES:
            # custom zone update
            if obj.name in self._zones:
                self._zones[obj.name] = obj
            return ("update", obj)
        else:
            if obj.name in self._builtin_zones:
                # builtin zone update
                del self._builtin_zones[obj.name]
                self._builtin_zones[obj.name] = obj

                if obj.name not in self._zones:
                    # update dbus zone
                    return ("update", obj)
                else:
                    # builtin hidden, no update needed
                    return (None, None)
            
        # zone not known to firewalld, yet (timeout, ..)
        return (None, None)

    def _remove_zone(self, obj):
        if obj.name not in self._zones:
            raise FirewallError(INVALID_ZONE,
                                "'%s' not in self._zones" % obj.name)
        if not obj.path.startswith(ETC_FIREWALLD_ZONES):
            raise FirewallError(INVALID_DIRECTORY,
                "'%s' doesn't start with '%s'" % (obj.path, ETC_FIREWALLD_ZONES))
        os.remove("%s/%s.xml" % (ETC_FIREWALLD_ZONES, obj.name))
        del self._zones[obj.name]

    def check_builtin_zone(self, obj):
        if obj.builtin:
            raise FirewallError(BUILTIN_ZONE, "'%s' is built-in zone" % obj.name)

    def remove_zone(self, obj):
        self.check_builtin_zone(obj)
        self._remove_zone(obj)

    def rename_zone(self, obj, name):
        self.check_builtin_zone(obj)
        new_zone = self._copy_zone(obj, name)
        self._remove_zone(obj)
        return new_zone

    def _copy_zone(self, obj, name):
        return self.new_zone(name, obj.export_config())
