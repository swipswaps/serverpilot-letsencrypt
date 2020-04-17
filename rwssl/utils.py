import os
from .tools import *
from termcolor import colored
import nginx
import json
import validators
from getpass import getpass

class ServerPilot:
    def __init__(self, username = False, app = False):
        self.mainroot = '/'
        self.usrdataroot = os.path.join(self.mainroot, 'srv', 'users')
        self.nginxroot = os.path.join(self.mainroot, 'etc', 'nginx-sp')
        self.sslroot = os.path.join(self.nginxroot, 'le-ssls')
        self.vhostdir = 'vhosts.d'
        self.username = username
        self.app = app
        self.domains = []

    def setuser(self, username):
        self.username = username

    def setapp(self, app):
        self.app = app

    def setdomains(self, domains):
        doms = domains.split(',')
        for dom in doms:
            if validators.domain(dom) is True:
                self.domains.append(dom)
            else:
                raise Exception('{} is not a valid domain.'.format(dom))
        if len(self.domains) == 0:
            raise Exception('You need to provide at least one valid domain name.')

    def usrhome(self):
        if not self.username:
            raise Exception('SSH username has not been provided.')
        return os.path.join(self.usrdataroot, self.username)

    def appsdir(self):
        return os.path.join(self.usrhome(), 'apps')

    def appdir(self):
        if not self.app:
            raise Exception('App name has not been provided.')
        return os.path.join(self.appsdir(), self.app)

    def appnginxconf(self):
        if not self.app:
            raise Exception('App name has not been provided.')
        return os.path.join(self.nginxroot, self.vhostdir, '{}.conf'.format(self.app))

    def isvalidapp(self):
        if self.appdetails():
            return True
        return False

    def appdetails(self):
        conff = os.path.join(self.nginxroot, self.vhostdir, '{}.conf'.format(self.app))
        if not os.path.exists(conff):
            raise Exception('Looks like you  provided a wrong app name.')
        c = nginx.loadf(conff)
        if len(c.filter('Server')) == 2:
            s = c.filter('Server')[1]
        else:
            s = c.filter('Server')[0]
        return {
            'domains': list(filter(None, s.filter('Key', 'server_name')[0].as_dict.get('server_name'))),
            'user': list(filter(None, c.filter('Server')[1].filter('Key', 'root')[0].as_dict.get('root').split('/')))[2]
        }

    def findapps(self):
        appsdata = []
        i = 0
        if not self.username:
            os.chdir(self.usrdataroot)
            users = list(filter(os.path.isdir, os.listdir(os.curdir)))
            if len(users):
                for user in users:
                    self.username = user
                    appsdir = self.appsdir()
                    if os.path.exists(appsdir):
                        os.chdir(appsdir)
                        apps = list(filter(os.path.isdir, os.listdir(os.curdir)))
                        for app in apps:
                            self.app = app
                            if self.isvalidapp():
                                i += 1
                                info = self.appdetails()
                                appsdata.append([i, self.app, info.get('user'), ','.join(info.get('domains'))])
        else:
            appsdir = self.appsdir()
            if not os.path.exists(appsdir):
                raise Exception('Looks like you have provided an invalid SSH user.')
            else:
                os.chdir(appsdir)
                apps = list(filter(os.path.isdir, os.listdir(os.curdir)))
                for app in apps:
                    self.app = app
                    if self.isvalidapp():
                        i += 1
                        info = self.appdetails()
                        appsdata.append([i, self.app, info.get('user'), ','.join(info.get('domains'))])
        return appsdata

    def gettpldata(self):
        if len(self.domains) > 1:
            serveralias = ''
        else:
            serveralias = False
        servername = ''
        di = 0
        for dom in self.domains:
            di += 1
            if di == 1:
                servername = dom
            else:
                if di > 2:
                    serveralias += ' '
                serveralias += dom
        return {
            'appname': self.app,
            'username': self.username,
            'servername': servername,
            'serveralias': serveralias
        }

    def createnginxvhost(self):
        data = self.gettpldata()
        nginxmaindata = parsetpl('nginx-main.tpl')
        with open(os.path.join(self.nginxroot, self.vhostdir, '{}.d'.format(self.app), 'main.conf'), 'w') as nginxmain:
            nginxmain.write(nginxmaindata)
        nginxtpldata = parsetpl('nginx.tpl', data=data)
        with open(self.appnginxconf(), 'w') as nginxconf:
            nginxconf.write(nginxtpldata)

    def createnginxsslvhost(self):
        data = self.gettpldata()
        data.update({'sslpath': self.sslroot})
        nginxtpldata = parsetpl('nginx-ssl.tpl', data=data)
        with open(self.appnginxconf(), 'w') as nginxconf:
            nginxconf.write(nginxtpldata)

    def createnginxsslforcedvhost(self):
        data = self.gettpldata()
        data.update({'sslpath': self.sslroot})
        nginxtpldata = parsetpl('nginx-sslforced.tpl', data=data)
        with open(self.appnginxconf(), 'w') as nginxconf:
            nginxconf.write(nginxtpldata)

    def reloadservices(self):
        restartservice('nginx-sp')

    def search(self, value, data):
        for conf in data:
            blocks = conf.get('server')
            for block in blocks:
                found = block.get(value)
                if found:
                    return found
        return None

    def getcert(self):
        if not self.isvalidapp():
            raise Exception('A valid app name is not provided.')
        with open(self.appnginxconf()) as nginxconf:
            nginxconfbackup = nginxconf.read()
        details = self.appdetails()
        self.setuser(details.get('user'))
        self.domains = details.get('domains')
        validdoms = []
        try:
            for domain in details.get('domains'):
                cmd = "certbot certonly --non-interactive --dry-run --webroot -w {} --register-unsafely-without-email --agree-tos -d {}".format(os.path.join(self.appdir(), 'public'), domain)
                runcmd(cmd)
                validdoms.append(domain)
        except Exception as e:
            print(str(e))
            pass

        if len(validdoms) > 0:
            domainsstr = ''
            webroot = os.path.join(self.appdir(), 'public')
            for vd in validdoms:
                domainsstr += ' -d {}'.format(vd)
            cmd = "certbot certonly --non-interactive --agree-tos --register-unsafely-without-email --webroot -w {} --cert-name {} --config-dir {}{}".format(webroot, self.app, self.sslroot, domainsstr)
            runcmd(cmd)
            self.createnginxsslvhost()
            try:
                reloadservice('nginx-sp')
                print(colored('SSL activated for app {} (Domains Secured: {})'.format(self.app, ' '.join(validdoms)), 'green'))
            except:
                try:
                    restartservice('nginx-sp')
                except:
                    with open(self.appnginxconf(), 'w') as restoreconf:
                        restoreconf.write(nginxconfbackup)
                    restartservice('nginx-sp')
                    raise Exception('SSL activation failed!')
        else:
            print('SSL not available for this app yet.')

    def apphasssl(self):
        return os.path.exists(os.path.join(self.sslroot, 'live', self.app, 'fullchain.pem'))

    def removecert(self):
        if not self.isvalidapp():
            raise Exception('A valid app name should be provided.')

        if not self.apphasssl():
            raise Exception('The app {} does not have an active SSL certificate.'.format(self.app))

        details = self.appdetails()
        self.domains = details.get('domains')
        self.setuser(details.get('user'))
        cmd = "certbot --non-interactive revoke --config-dir {} --cert-name {}".format(self.sslroot, self.app)
        try:
            runcmd(cmd)
            self.createnginxvhost()
            try:
                reloadservice('nginx-sp')
            except:
                restartservice('nginx-sp')

        except Exception as e:
            raise Exception("SSL certificate cannot be removed: {}".format(str(e)))

    def forcessl(self):
        if not self.isvalidapp():
            raise Exception('A valid app name should be provided.')
        if not self.apphasssl():
            raise Exception('The app {} does not have an active SSL certificate.'.format(self.app))
        details = self.appdetails()
        self.setuser(details.get('user'))
        self.domains = details.get('domains')
        self.createnginxsslforcedvhost()
        try:
            reloadservice('nginx-sp')
        except:
            restartservice('nginx-sp')

    def unforcessl(self):
        if not self.isvalidapp():
            raise Exception('A valid app name should be provided.')
        details = self.appdetails()
        self.setuser(details.get('user'))
        self.domains = details.get('domains')
        if self.apphasssl():
            self.createnginxsslvhost()
        else:
            self.createnginxvhost()
        try:
            reloadservice('nginx-sp')
        except:
            restartservice('nginx-sp')
