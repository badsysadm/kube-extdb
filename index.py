#!/usr/bin/env python3
import psycopg2
import base64
import json
import requests
import time

serviceTemplate = {
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

endpointTemplate = {
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
    """Kubernetes parameters and methods for api"""
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

class pgc(object):
    """Work with CRD pgclusters"""
    def __init__(self, data, namespace):
        self.name = data['metadata']['name']
        self.namespace = namespace
        self.pg_secret = data['spec']['secret']
        self.pg_hosts = data['spec']['hosts']
        svc = serviceTemplate
        ep = endpointTemplate
        svc['metadata']['labels']['app'] = self.name
        svc['metadata']['name'] = self.name
        ep['metadata']['labels']['app'] = self.name
        ep['metadata']['name'] = self.name
        self.serviceTemplate = svc
        self.endpointTemplate = ep
    def get_secret(self):
        #Get secret for postgres user with needed privileges
        getSecret = kubeData('/api/v1/namespaces/' + self.namespace + '/secrets/' + self.pg_secret)
        pg_secret = getSecret.get()['data']
        self.pg_pass = base64.b64decode(pg_secret['password']).decode("utf-8")
        self.pg_user = base64.b64decode(pg_secret['username']).decode("utf-8")
        self.pg_db = base64.b64decode(pg_secret['database']).decode("utf-8")
        return True
    def get_master(self):
        #Get info about Master-node in postgres-cluster
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
        #Create service-resource for external postgres
        svcNames = []
        svcKube = kubeData('/api/v1/namespaces/' + self.namespace + '/services')
        getSVC = svcKube.get()['items']
        for svc in getSVC:
            svcNames.append(svc['metadata']['name'])

        if self.name not in svcNames:
            headers = {'Content-Type': 'application/json'}
            self.serviceTemplate['spec']['ports'].clear()
            self.serviceTemplate['spec']['ports'].append({ "port": int(self.master_port), "protocol": "TCP", "targetPort": int(self.master_port) })
            self.endpointTemplate['subsets'].clear()
            self.endpointTemplate['subsets'].append(self.ip_master)

            svcKube.post(self.serviceTemplate)
            epKube = kubeData('/api/v1/namespaces/' + self.namespace + '/endpoints')
            epKube.post(self.endpointTemplate)
        return True
    def create_endpoint(self):
        #Edit endpoints for service-resource
        endpointTemplate['subsets'].clear()
        endpointTemplate['subsets'].append(self.ip_master)
        endpointsKube = kubeData('/api/v1/namespaces/' + self.namespace + '/endpoints/' + self.name)
        endpointsKube.put(self.endpointTemplate)
        return True

def main():
    #Get list of namespaces
    nsKube = kubeData('/api/v1/namespaces/')
    getNS = nsKube.get()
    for ns in getNS['items']:
        namespace = ns['metadata']['name']
        #Get CRD
        pgcKube = kubeData('/apis/stable.badsysadm.com/v1/namespaces/' + namespace + '/pgclusters')
        getCRD = pgcKube.get()
        for res in getCRD['items']:
            pgc_res = pgc(res, namespace)
            pgc_res.get_secret()
            pgc_res.get_master()
            pgc_res.create_service()
            pgc_res.create_endpoint()

if __name__ == "__main__":
    while True:
        main()
        time.sleep(5)

