#!/usr/bin/env python3
import psycopg2
import base64
import json
import requests
import time
from redis.sentinel import Sentinel

svcTemplate = {
    "apiVersion": "v1",
    "kind": "Service",
    "metadata": {
        "labels": {
            "app": "name"
        },
        "name": "name"
    },
    "spec": {
        "ports": [ ]
    }
}

epTemplate = {
    "apiVersion": "v1",
    "kind": "Endpoints",
    "metadata": {
        "labels": {
            "app": "name"
        },
        "name": "name"
    },
    "subsets": [ ]
}

class kubeData(object):
    def __init__(self, url):
        self.headers = {'Content-Type': 'application/json'}
        self.url = url
        self.ca = '/etc/kubernetes/pki/ca/ca.pem'
        self.cert = '/etc/kubernetes/pki/key/admin.pem'
        self.key = '/etc/kubernetes/pki/key/admin-key.pem'
        self.host = 'https://127.0.0.1:6443'
    def get(self):
        getData = requests.get(self.host + self.url , verify=self.ca, cert=(self.cert, self.key))
        data = json.loads(getData.text)
        return data
    def post(self, data):
        postData = requests.post(self.host + self.url, verify=self.ca, cert=(self.cert, self.key), data=json.dumps(data), headers=self.headers)
        data = json.loads(postData.text)
        print(data)
        return data
    def put(self, data):
        putData = requests.put(self.host + self.url, verify=self.ca, cert=(self.cert, self.key), data=json.dumps(data), headers=self.headers)
        data = json.loads(putData.text)
        return data

class rdc(object):
    def __init__(self, data, namespace):
        self.name = data['metadata']['name']
        self.namespace = namespace
        self.redis_auth = data['spec']['secret']
        self.redis_hosts = data['spec']['hosts']
        svc = svcTemplate
        ep = epTemplate
        svc['metadata']['labels']['app'] = self.name
        svc['metadata']['name'] = self.name
        ep['metadata']['labels']['app'] = self.name
        ep['metadata']['name'] = self.name
        self.svcTemplate = svc
        self.epTemplate = ep
    def get_secret(self):
        getSecret = kubeData('/api/v1/namespaces/' + self.namespace + '/secrets/' + self.redis_auth)
        redis_secret = getSecret.get()['data']
        self.redis_password = base64.b64decode(redis_secret['auth']).decode("utf-8")
        return True
    def get_master(self):
        print (self.redis_hosts)
        sentinel_hosts = []
        for redis_host in self.redis_hosts:
            redis_address_array = redis_host.split(':')
            redis_ip = redis_address_array[0]
            redis_port = redis_address_array[1]
            address = (redis_ip, redis_port)
            sentinel_hosts.append( address )

        print (sentinel_hosts)

        sentinel = Sentinel([('192.168.206.41', 26379), ('192.168.206.42', 26379), ('192.168.206.43', 26379)], socket_timeout=0.1)
        print(sentinel.discover_master('mymaster'))
        master = sentinel.discover_master('mymaster')
        self.master_ip = master[0]
        self.master_port = master[1]
        print(str(master[0]) + ' is master')
        self.ip_master = {"addresses": [{"ip": self.master_ip}], "ports": [ { "port": int(self.master_port), "protocol": "TCP" } ] }
        return True
    def create_service(self):
        svcNames = []
        svcKube = kubeData('/api/v1/namespaces/' + self.namespace + '/services')
        getSVC = svcKube.get()['items']
        for svc in getSVC:
            svcNames.append(svc['metadata']['name'])

        if self.name not in svcNames:
            headers = {'Content-Type': 'application/json'}
            self.svcTemplate['spec']['ports'].clear()
            self.svcTemplate['spec']['ports'].append({ "port": int(self.master_port), "protocol": "TCP", "targetPort": int(self.master_port) })
            self.epTemplate['subsets'].clear()
            self.epTemplate['subsets'].append(self.ip_master)

            svcKube.post(self.svcTemplate)
            epKube = kubeData('/api/v1/namespaces/' + self.namespace + '/endpoints')
            epKube.post(self.epTemplate)
        return True
    def create_endpoint(self):
        epTemplate['subsets'].clear()
        epTemplate['subsets'].append(self.ip_master)
        epKube = kubeData('/api/v1/namespaces/' + self.namespace + '/endpoints/' + self.name)
        epKube.put(self.epTemplate)
        return True

class pgc(object):
    """docstring"""
    def __init__(self, data, namespace):
        self.name = data['metadata']['name']
        self.namespace = namespace
        self.pg_secret = data['spec']['secret']
        self.pg_hosts = data['spec']['hosts']
        svc = svcTemplate
        ep = epTemplate
        svc['metadata']['labels']['app'] = self.name
        svc['metadata']['name'] = self.name
        ep['metadata']['labels']['app'] = self.name
        ep['metadata']['name'] = self.name
        self.svcTemplate = svc
        self.epTemplate = ep
    def get_secret(self):
        getSecret = kubeData('/api/v1/namespaces/' + self.namespace + '/secrets/' + self.pg_secret)
        pg_secret = getSecret.get()['data']
        self.pg_pass = base64.b64decode(pg_secret['password']).decode("utf-8")
        self.pg_user = base64.b64decode(pg_secret['username']).decode("utf-8")
        self.pg_db = base64.b64decode(pg_secret['database']).decode("utf-8")
        return True
    def get_master(self):
        print (self.pg_hosts)
        for pg_host in self.pg_hosts:
            pg_address_array = pg_host.split(':')
            pg_ip = pg_address_array[0]
            pg_port = pg_address_array[1]
            try:
                conn = psycopg2.connect(dbname=self.pg_db, user=self.pg_user,
                                        password=self.pg_pass, host=pg_ip, port=pg_port)
                cursor = conn.cursor()
                cursor.execute('select pg_is_in_recovery()')
                records = cursor.fetchall()
            except:
                print(pg_host + ': failed to connect')
                continue
            if records[0][0] == False:
                print(pg_host + ' is master')
                self.master_ip = pg_ip
                self.master_port = pg_port
                self.ip_master = {"addresses": [{"ip": pg_ip}], "ports": [ { "port": int(pg_port), "protocol": "TCP" } ] }
            else:
                print(pg_host + ' is slave')
            cursor.close()
            conn.close()
        return True
    def create_service(self):
        svcNames = []
        svcKube = kubeData('/api/v1/namespaces/' + self.namespace + '/services')
        getSVC = svcKube.get()['items']
        for svc in getSVC:
            svcNames.append(svc['metadata']['name'])

        if self.name not in svcNames:
            headers = {'Content-Type': 'application/json'}
            self.svcTemplate['spec']['ports'].clear()
            self.svcTemplate['spec']['ports'].append({ "port": int(self.master_port), "protocol": "TCP", "targetPort": int(self.master_port) })
            self.epTemplate['subsets'].clear()
            self.epTemplate['subsets'].append(self.ip_master)

            svcKube.post(self.svcTemplate)
            epKube = kubeData('/api/v1/namespaces/' + self.namespace + '/endpoints')
            epKube.post(self.epTemplate)
        return True
    def create_endpoint(self):
        epTemplate['subsets'].clear()
        epTemplate['subsets'].append(self.ip_master)
        epKube = kubeData('/api/v1/namespaces/' + self.namespace + '/endpoints/' + self.name)
        epKube.put(self.epTemplate)
        return True

def main():
    nsKube = kubeData('/api/v1/namespaces/')
    getNs = nsKube.get()
    for ns in getNs['items']:
        namespace = ns['metadata']['name']

        rdcKube = kubeData('/apis/stable.badsysadm.com/v1/namespaces/' + namespace + '/redisclusters')
        pgcKube = kubeData('/apis/stable.badsysadm.com/v1/namespaces/' + namespace + '/pgclusters')
        rdc_getRes = rdcKube.get()
        pgc_getRes = pgcKube.get()

        for res in rdc_getRes['items']:
            rdc_res = rdc(res, namespace)
            rdc_res.get_secret()
            rdc_res.get_master()
            rdc_res.create_service()
            rdc_res.create_endpoint()

        for res in pgc_getRes['items']:
            pgc_res = pgc(res, namespace)
            pgc_res.get_secret()
            pgc_res.get_master()
            pgc_res.create_service()
            pgc_res.create_endpoint()

if __name__ == "__main__":
    while True:
        main()
        time.sleep(5)
