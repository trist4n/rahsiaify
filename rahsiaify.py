#from flask import Flask, request, session, g, redirect, url_for, abort, render_template, flash
from flask import Flask, request, render_template
import threading
import os
import logging
import requests
import urllib as urllibparse
import sqlite3
import uuid
import base64
import fileinput
import random
import json
from time import gmtime, strftime

if "DEBUG" in os.environ:
    import httplib as http_client
    http_client.HTTPConnection.debuglevel = 1
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.DEBUG)
    requests_log.propagate = True

app = Flask("rahsiaify")

try:
    config = {
        "CLIENT_ID": os.environ["RAHSIAIFY_CLIENT_ID"],
        "CLIENT_SECRET": os.environ["RAHSIAIFY_CLIENT_SECRET"],
        "SERVER_NAME": "localhost:8888",
    }
except KeyError as e:
    logging.fatal("need RAHSIAIFY_CLIENT_ID and RAHSIAIFY_CLIENT_SECRET env variables")
    raise e
app.config.update(config)

def connect_db():
    ## we will do our own synchronisation
    rv = sqlite3.connect("rahsiaify.db", check_same_thread=False)
    rv.row_factory = sqlite3.Row
    return rv



db = connect_db()
db.execute("create table if not exists tokens (id string primary key, access_code string, access_token string, refresh_token string, expires_in int)")

@app.route('/callback')
def callback():
    ## save initial result
    id = uuid.uuid4()
    code = request.args.get('code', '')
    state = request.args.get('state', '')
    db.execute("insert into tokens (id,access_code) values(?,?)", (str(id), code))

    ## convert into tokens
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://%s/callback" % (config["SERVER_NAME"]),
        "client_id": config["CLIENT_ID"],
        "client_secret": config["CLIENT_SECRET"],
    }

    r = requests.post('https://accounts.spotify.com/api/token', data = payload)
    if r.status_code != 200:
        logging.fatal(r.text)
    data = r.json()

    db.execute("update tokens set access_token=?, refresh_token=?, expires_in=? where id=?", (data["access_token"],data["refresh_token"],data["expires_in"],str(id)))
    db.commit()

    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return "Shutting down..."

def call_authorize():
    payload = {
        "client_id": config["CLIENT_ID"],
        "response_type": "code",
        "redirect_uri": "http://%s/callback" % (config["SERVER_NAME"]),
        "scope": "user-top-read playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public",
    }
    urlparams = urllibparse.urlencode(payload)
    url = "%s?%s" % ('https://accounts.spotify.com/authorize/', urlparams)
    print "pls call " + url

def get_auth_header(atoken):
    h = {
        "Authorization": "Bearer %s" % (atoken)
    }
    return h

def get_top_tracks(atoken):
    r = requests.get("https://api.spotify.com/v1/me/top/tracks", headers=get_auth_header(atoken))
    print r.text

def get_self(atoken):
    r = requests.get("https://api.spotify.com/v1/me", headers=get_auth_header(atoken))
    return r.json()

def get_user_playlists(atoken, userid):
    r = requests.get("https://api.spotify.com/v1/users/%s/playlists" % (userid), headers=get_auth_header(atoken))
    return r.json()

def get_playlist_tracks(atoken, userid, playlistid):
    r = requests.get("https://api.spotify.com/v1/users/%s/playlists/%s/tracks" % (userid,playlistid), headers=get_auth_header(atoken))
    return r.json()


def new_playlist(atoken, userid, songlist):
    id = "mixup: %s" % (strftime("%Y-%m-%d %H:%M:%S", gmtime()))
    payload = {
        "name": str(id),
        "public": False,
    }
    sh = get_auth_header(atoken),
    headers = {
        "Content-Type": "application/json",
        "Authorization": sh[0],
    }
    r = requests.post('https://api.spotify.com/v1/users/%s/playlists' % (userid),
        data = json.dumps(payload),
        headers = headers,
    )

    data = r.json()
    print "adding tracks to %s (%s)" % (id, data["id"])

    songs = ["spotify:track:%s" % (s) for s in songlist]
    print songs
    r = requests.post('https://api.spotify.com/v1/users/%s/playlists/%s/tracks' % (userid,data["id"]),
        data = json.dumps({
            "uris": songs
        }),
        headers = headers,
    )
    return r.json()

## have existing token?
row = db.execute("select id, access_token, refresh_token from tokens").fetchone()
if not row:
    ## run webserver thread to catch authentication callback
    webthread = threading.Thread(target = lambda : app.run())

    webthread.start()
    call_authorize()
    webthread.join()

    row = db.execute("select id, access_token, refresh_token from tokens").fetchone()
    assert row

(id, atoken, rtoken) = row
print "id=%s, atoken=%s, rtoken=%s" % (id,atoken,rtoken)
self =  get_self(atoken)

playlists =  get_user_playlists(atoken, self["id"])
for i in range(0,len(playlists["items"])):
    print "[%d] %s" % (i,playlists["items"][i]["name"])

print "first playlist choice: ",
first = int(raw_input())
print "second playlist choice: ",
second = int(raw_input())

print "shuffling between %s and %s" % (playlists["items"][first]["name"], playlists["items"][second]["name"])
first_tracks = get_playlist_tracks(atoken, self["id"], playlists["items"][first]["id"])
second_tracks = get_playlist_tracks(atoken, self["id"], playlists["items"][second]["id"])

## build a list of 24 random songs from both
uris = []
for i in range(0,12):
    ftrack = random.choice(first_tracks["items"])
    uris.append(ftrack["track"]["id"])
    print "adding %s" % (ftrack["track"]["name"])

    strack = random.choice(second_tracks["items"])
    uris.append(strack["track"]["id"])
    print "adding %s" % (strack["track"]["name"])

print new_playlist(atoken, self["id"], uris)
