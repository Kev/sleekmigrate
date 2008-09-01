#!/usr/bin/python2.5
"""
    This file is part of SleekMigrate.

    SleekMigrate is free software; you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation; either version 2 of the License, or
    (at your option) any later version.

    SleekMigrate is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with SleekMigrate; if not, write to the Free Software
    Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
"""

import logging
import sleekxmpp.sleekxmpp as sleekxmpp
from optparse import OptionParser
from xml.etree import cElementTree as ET

import os
import time
import csv
import codecs

class Account(object):
    def __init__(self, jid, password):
        self.jid = jid
        self.password = password
        self.rosterEntries = []
        
    def host(self):
        return self.splitJid()[1]
        
    def user(self):
        return self.splitJid()[0]
        
    def splitJid(self):
        return self.jid.split("@")
        
    def getVcardElement(self):
        return self.vcardElement
    
    def getPrivateElements(self):
        return self.privateElements
    
        
class RosterEntry(object):
    def __init__(self, jid, groups, name, subscription):
        self.jid = jid
        self.groups = groups
        self.name = name
        self.subscription = subscription

class TigaseCSVExporter(object):
    def __init__(self, fileName):
        self.out = file(fileName, "w")
        
    def export(self, user):
        logging.info("Exporting account " + user.jid)
        for rosterEntry in user.rosterEntries:
            if len(rosterEntry.groups) == 0:
                rosterEntry.groups = ("")
            if rosterEntry.groups[0] is None:
                rosterEntry.groups = ("")
            if len(rosterEntry.groups > 1):
                rosterEntry.groups = (rosterEntry.groups[0])
            for group in rosterEntry.groups:
                self.out.write("%s,%s,%s,%s,%s,%s\n" % (user.jid, user.password, rosterEntry.jid, rosterEntry.name, rosterEntry.subscription, group))
        
    def finalise(self):
        self.out.close()

class XEP0227Exporter(object):
    def __init__(self, fileName):
        self.fileName = fileName
        self.element = ET.Element('{http://www.xmpp.org/extensions/xep-0227.html#ns}server-data')
        self.hostElements = {}
        
    def elementForHost(self, host):
        hostElement = self.hostElements.get(host, None)
        if hostElement is None:
            hostElement = ET.Element('host')
            hostElement.set('jid', host)
            self.hostElements[host] = hostElement
            self.element.append(hostElement)
        return hostElement
        
    def export(self, user):
        logging.info("Exporting account " + user.jid)
        userElement = ET.Element('user')
        userElement.set('name', user.user())
        userElement.set('password', user.password)
        rosterElement = ET.Element('{jabber:iq:roster}query')
        for rosterEntry in user.rosterEntries:
            itemElement = ET.Element('item')
            itemElement.set('jid', rosterEntry.jid)
            if rosterEntry.name:
                itemElement.set('name', rosterEntry.name)
            itemElement.set('subscription', rosterEntry.subscription)
            for group in rosterEntry.groups:
                if group is not None:
                    groupElement = ET.Element('group')
                    groupElement.text = group
                    itemElement.append(groupElement)
            rosterElement.append(itemElement)
        userElement.append(rosterElement)
        if user.vcardElement is not None:
            userElement.append(user.vcardElement)
        if len(user.privateElements) > 0:
            privateElement = ET.Element('{jabber:iq:private}query')
            for privateSubElement in user.privateElements:
                privateElement.append(privateSubElement)
            userElement.append(privateElement)
        
        self.elementForHost(user.host()).append(userElement)
        
    def finalise(self):
        ET.ElementTree(self.element).write(self.fileName)

class XMPPAccountExtractor(sleekxmpp.xmppclient):
    def __init__(self, jid, password, ssl=False, plugin_config = {}, plugin_whitelist=[]):
        sleekxmpp.xmppclient.__init__(self, jid, password, ssl, plugin_config, plugin_whitelist)
        logging.info("Logging in as %s" % self.jid)
        self.add_event_handler("session_start", self.start, threaded=True)
        self.add_event_handler("roster_update", self.receive_roster)
        self.account = Account(jid, password)
        self.rosterDone = False
        self.vcardDone = False
        self.privatesDone = False
        self.sessionOkay = False
        self.timeout = 30
        self.privatesToRequest = ("{exodus:prefs}exodus","{storage:bookmarks}storage", "{storage:rosternotes}storage", "{storage:metacontacts}storage")
	
    def start(self, event):
        self.sessionOkay = True
        self.requestRoster()
        
        while not self.vcardDone or not self.rosterDone or not self.privatesDone:
            time.sleep(1)
        self.disconnect()
	

		
    def fetch_privates(self):
        self.account.privateElements = []
        for privateToRequest in self.privatesToRequest:
            id = self.getNewId()
            iq = self.makeIq(id)
            iq.attrib['type'] = "get"
            iqRequestElement = ET.Element("{jabber:iq:private}query")
            iq.append(iqRequestElement)
            iqRequestElement.append(ET.Element(privateToRequest))
            iqResult = self.send(iq, self.makeIq(id), self.timeout)
            if iqResult is not None:
                midResult = iqResult.find("{jabber:iq:private}query")
                if midResult is not None:
                    result = midResult.find(privateToRequest)
                    if result is not None:
                        self.account.privateElements.append(result)
        self.privatesDone = True

    def fetch_vcard(self):
        id = self.getNewId()
        iq = self.makeIq(id)
        iq.attrib['type'] = "get"
        vcardRequestElement = ET.Element("{vcard-temp}vCard")
        iq.append(vcardRequestElement)
        vcardResult = self.send(iq, self.makeIq(id), self.timeout)
        self.account.vcardElement = vcardResult.find("{vcard-temp}vCard")
        self.vcardDone = True
        self.fetch_privates()

			

    def receive_roster(self, event):
        for jid in event:
            self.account.rosterEntries.append(RosterEntry(jid, event[jid]['groups'], event[jid]['name'], event[jid]['subscription']))
        self.rosterDone = True
        self.fetch_vcard()
    
    def export_okay(self):
        return self.sessionOkay
        
    def getAccount(self):
        return self.account

def authDetailsFromFile(filename):
    """ Return a list of auth dicts
    """
    logging.warn("The import method isn't unicode-safe, yet")
    reader = csv.reader(open(filename, "rb"))
    auths = []
    for row in reader:
        auths.append({'jid':row[0],'pass':row[1]})
    return auths

if __name__ == '__main__':
    #parse command line arguements
    optp = OptionParser()
    optp.add_option('-q','--quiet', help='set logging to ERROR', action='store_const', dest='loglevel', const=logging.ERROR, default=logging.INFO)
    optp.add_option('-d','--debug', help='set logging to DEBUG', action='store_const', dest='loglevel', const=logging.DEBUG, default=logging.INFO)
    optp.add_option('-v','--verbose', help='set logging to COMM', action='store_const', dest='loglevel', const=5, default=logging.INFO)
    optp.add_option("-e","--export-formatter", dest="exportFormatter",  type='choice', default="xep0227", choices=("xep0227","tigase"), help="formatter for exported data")
    optp.add_option('-s','--server', help='domain to export', dest='hostname', default=None)
    #optp.add_option("-c","--config", dest="configfile", default="config.xml", help="set config file to use")
    optp.add_option("-f","--user-file", dest="userFile", default="users.csv", help="name of CSV uname/password pairs file")
    opts,args = optp.parse_args()
	
    logging.basicConfig(level=opts.loglevel, format='%(levelname)-8s %(message)s')

    logging.info("Loading user file: %s" % opts.userFile)
    authDetails = authDetailsFromFile(opts.userFile)

    plugin_config = {}
    exporterType = opts.exportFormatter
    if exporterType == "xep0227":
        exporter =  XEP0227Exporter('227.xml')
    elif exporterType == "tigase":
        exporter = TigaseCSVExporter('out.txt')
    else:
        logging.error("Unexpected Exporter type %s." % exporterType)
	
    for auth in authDetails:
        extractor = XMPPAccountExtractor(auth['jid'], auth['pass'], plugin_config=plugin_config, plugin_whitelist=[])
        if opts.hostname is None:
            extractor.connect() 
        else:
            extractor.connect((opts.hostname, 5222))
        extractor.process()
        while extractor.connected:
            time.sleep(1)
        if extractor.export_okay():
            exporter.export(extractor.getAccount())
    exporter.finalise()
