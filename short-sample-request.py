#!/usr/bin/env python3

import requests
import json, jsonpickle
import os
import sys
import base64
import glob


#

#REST="ingress ip" -> kubectl get ingress rest-ingress -w
REST = os.getenv("REST") or "localhost"
print(f"REST is {REST}")
#export CALLBACK_URL="http://rest:5000"
CALLBACK_URL = f"http://{REST}"
print(f"CALLBACK_URL is {CALLBACK_URL}")
##
# The following routine makes a JSON REST query of the specified type
# and if a successful JSON reply is made, it pretty-prints the reply
##

def mkReq(reqmethod, endpoint, data, verbose=True):
    print(f"Response to http://{REST}/{endpoint} request is {type(data)}")
    url = f"http://{REST}/{endpoint}"
    # GCE (and many proxies) return 400 if GET includes a body; use bare GET for queue.
    if data is None:
        response = reqmethod(url)
    else:
        jsonData = jsonpickle.encode(data)
        if verbose:
            print(f"Make request http://{REST}/{endpoint} with json {data.keys()}")
            print(f"mp3 is of type {type(data['mp3'])} and length {len(data['mp3'])} ")
        response = reqmethod(
            url, data=jsonData, headers={"Content-type": "application/json"}
        )
    if response.status_code == 200:
        jsonResponse = json.dumps(response.json(), indent=4, sort_keys=True)
        print(jsonResponse)
        return
    else:
        print(
            f"response code is {response.status_code}, raw response is {response.text}")
        return response.text


for mp3 in glob.glob("data/short*mp3"):
    print(f"Separate data/{mp3}")
    mkReq(requests.post, "apiv1/separate",
        data={
            "mp3": base64.b64encode( open(mp3, "rb").read() ).decode('utf-8'),
            "callback": {
                "url": CALLBACK_URL,
                "data": {"mp3": mp3,
                         "data": "to be returned"}
            }
        },
        verbose=True
        )
    print(f"Cache from server is")
    mkReq(requests.get, "apiv1/queue", data=None)

# to download the tracks
"""
curl -fL -o bass.mp3    "http://${REST}/apiv1/track/${HASH}/bass.mp3"
curl -fL -o drums.mp3   "http://${REST}/apiv1/track/${HASH}/drums.mp3"
curl -fL -o vocals.mp3  "http://${REST}/apiv1/track/${HASH}/vocals.mp3"
curl -fL -o other.mp3   "http://${REST}/apiv1/track/${HASH}/other.mp3"
"""

sys.exit(0)

