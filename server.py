#!/usr/bin/env python3.5
from flask import Flask, render_template, request, Response, jsonify
import json
import redis
import random, math
import configparser
from time import gmtime as now
from time import sleep, strftime
import datetime
import os

import util
import contributor_helper

configfile = os.path.join(os.environ['DASH_CONFIG'], 'config.cfg')
cfg = configparser.ConfigParser()
cfg.read(configfile)

app = Flask(__name__)

redis_server_log = redis.StrictRedis(
        host=cfg.get('RedisGlobal', 'host'),
        port=cfg.getint('RedisGlobal', 'port'),
        db=cfg.getint('RedisLog', 'db'))
redis_server_map = redis.StrictRedis(
        host=cfg.get('RedisGlobal', 'host'),
        port=cfg.getint('RedisGlobal', 'port'),
        db=cfg.getint('RedisMap', 'db'))
serv_redis_db = redis.StrictRedis(
        host=cfg.get('RedisGlobal', 'host'),
        port=cfg.getint('RedisGlobal', 'port'),
        db=cfg.getint('RedisDB', 'db'))

contributor_helper = contributor_helper.Contributor_helper(serv_redis_db, cfg)

subscriber_log = redis_server_log.pubsub(ignore_subscribe_messages=True)
subscriber_log.psubscribe(cfg.get('RedisLog', 'channel'))
subscriber_map = redis_server_map.pubsub(ignore_subscribe_messages=True)
subscriber_map.psubscribe(cfg.get('RedisMap', 'channelDisp'))
subscriber_lastContrib = redis_server_log.pubsub(ignore_subscribe_messages=True)
subscriber_lastContrib.psubscribe(cfg.get('RedisLog', 'channelLastContributor'))
subscriber_lastAwards = redis_server_log.pubsub(ignore_subscribe_messages=True)
subscriber_lastAwards.psubscribe(cfg.get('RedisLog', 'channelLastAwards'))

eventNumber = 0

##########
## UTIL ##
##########

''' INDEX '''
class LogItem():

    FIELDNAME_ORDER = []
    FIELDNAME_ORDER_HEADER = []
    FIELDNAME_ORDER.append("Time")
    FIELDNAME_ORDER_HEADER.append("Time")
    for item in json.loads(cfg.get('Log', 'fieldname_order')):
        if type(item) is list:
            FIELDNAME_ORDER_HEADER.append(" | ".join(item))
        else:
            FIELDNAME_ORDER_HEADER.append(item)
        FIELDNAME_ORDER.append(item)

    def __init__(self, feed):
        self.time = strftime("%H:%M:%S", now())
        #FIXME Parse feed message?
        self.fields = []
        self.fields.append(self.time)
        for f in feed:
            self.fields.append(f)

    def get_head_row(self):
        to_ret = []
        for fn in LogItem.FIELDNAME_ORDER_HEADER:
            to_ret.append(fn)
        return to_ret

    def get_row(self):
        to_ret = {}
        #Number to keep them sorted (jsonify sort keys)
        for item in range(len(LogItem.FIELDNAME_ORDER)):
            try:
                to_ret[item] = self.fields[item]
            except IndexError: # not enough field in rcv item
                to_ret[item] = ''
        return to_ret


class EventMessage():
    # Suppose the event message is a json with the format {name: 'feedName', log:'logData'}
    def __init__(self, msg):
        msg = msg.decode('utf8')
        try:
            jsonMsg = json.loads(msg)
        except json.JSONDecodeError:
            print('json decode error')
            jsonMsg = { 'name': "undefined" ,'log': json.loads(msg) }

        self.feedName = jsonMsg['name']
        self.zmqName = jsonMsg['zmqName']
        self.feed = json.loads(jsonMsg['log'])
        self.feed = LogItem(self.feed).get_row()

    def to_json(self):
        to_ret = { 'log': self.feed, 'feedName': self.feedName, 'zmqName': self.zmqName }
        return 'data: {}\n\n'.format(json.dumps(to_ret))

''' GENERAL '''
def getZrange(keyCateg, date, topNum, endSubkey=""):
    date_str = util.getDateStrFormat(date)
    keyname = "{}:{}{}".format(keyCateg, date_str, endSubkey)
    data = serv_redis_db.zrange(keyname, 0, topNum-1, desc=True, withscores=True)
    data = [ [record[0].decode('utf8'), record[1]] for record in data ]
    return data

###########
## ROUTE ##
###########

''' MAIN ROUTE '''

@app.route("/")
def index():
    ratioCorrection = 88
    pannelSize = [
            "{:.0f}".format(cfg.getint('Dashboard' ,'size_openStreet_pannel_perc')/100*ratioCorrection),
            "{:.0f}".format((100-cfg.getint('Dashboard' ,'size_openStreet_pannel_perc'))/100*ratioCorrection),
            "{:.0f}".format(cfg.getint('Dashboard' ,'size_world_pannel_perc')/100*ratioCorrection),
            "{:.0f}".format((100-cfg.getint('Dashboard' ,'size_world_pannel_perc'))/100*ratioCorrection)
            ]
    return render_template('index.html',
            pannelSize=pannelSize,
            size_dashboard_width=[cfg.getint('Dashboard' ,'size_dashboard_left_width'), 12-cfg.getint('Dashboard', 'size_dashboard_left_width')],
            itemToPlot=cfg.get('Dashboard', 'item_to_plot'),
            graph_log_refresh_rate=cfg.getint('Dashboard' ,'graph_log_refresh_rate'),
            char_separator=cfg.get('Log', 'char_separator'),
            rotation_wait_time=cfg.getint('Dashboard' ,'rotation_wait_time'),
            max_img_rotation=cfg.getint('Dashboard' ,'max_img_rotation'),
            hours_spanned=cfg.getint('Dashboard' ,'hours_spanned'),
            zoomlevel=cfg.getint('Dashboard' ,'zoomlevel')
            )


@app.route("/geo")
def geo():
    return render_template('geo.html',
            zoomlevel=cfg.getint('GEO' ,'zoomlevel'),
            default_updateFrequency=cfg.getint('GEO' ,'updateFrequency')
            )

@app.route("/contrib")
def contrib():
    categ_list = contributor_helper.categories_in_datatable
    categ_list_str = [ s[0].upper() + s[1:].replace('_', ' ') for s in categ_list]
    categ_list_points = [contributor_helper.DICO_PNTS_REWARD[categ] for categ in categ_list]

    org_rank = contributor_helper.org_rank
    org_rank_requirement_pnts = contributor_helper.org_rank_requirement_pnts
    org_rank_requirement_text = contributor_helper.org_rank_requirement_text
    org_rank_list = [[rank, title, org_rank_requirement_pnts[rank], org_rank_requirement_text[rank]] for rank, title in org_rank.items()]
    org_rank_list.sort(key=lambda x: x[0])
    org_rank_additional_text = contributor_helper.org_rank_additional_info

    org_honor_badge_title = contributor_helper.org_honor_badge_title
    org_honor_badge_title_list = [ [num, text] for num, text in contributor_helper.org_honor_badge_title.items()]
    org_honor_badge_title_list.sort(key=lambda x: x[0])

    trophy_categ_list = contributor_helper.categories_in_trophy
    trophy_categ_list_str = [ s[0].upper() + s[1:].replace('_', ' ') for s in trophy_categ_list]
    trophy_title = contributor_helper.trophy_title

    currOrg = request.args.get('org')
    if currOrg is None:
        currOrg = ""
    return render_template('contrib.html',
            currOrg=currOrg,
            rankMultiplier=contributor_helper.rankMultiplier,
            default_pnts_per_contribution=contributor_helper.default_pnts_per_contribution,
            additional_help_text=json.loads(cfg.get('CONTRIB', 'additional_help_text')),
            categ_list=json.dumps(categ_list),
            categ_list_str=categ_list_str,
            categ_list_points=categ_list_points,
            org_rank_json=json.dumps(org_rank),
            org_rank_list=org_rank_list,
            org_rank_additional_text=org_rank_additional_text,
            org_honor_badge_title=json.dumps(org_honor_badge_title),
            org_honor_badge_title_list=org_honor_badge_title_list,
            trophy_categ_list=json.dumps(trophy_categ_list),
            trophy_categ_list_id=trophy_categ_list,
            trophy_categ_list_str=trophy_categ_list_str,
            trophy_title=json.dumps(trophy_title),
            min_between_reload=cfg.getint('CONTRIB', 'min_between_reload')
            )

''' INDEX '''

@app.route("/_logs")
def logs():
    return Response(event_stream_log(), mimetype="text/event-stream")

@app.route("/_maps")
def maps():
    return Response(event_stream_maps(), mimetype="text/event-stream")

@app.route("/_get_log_head")
def getLogHead():
    return json.dumps(LogItem('').get_head_row())

def event_stream_log():
    for msg in subscriber_log.listen():
        content = msg['data']
        yield EventMessage(content).to_json()

def event_stream_maps():
    for msg in subscriber_map.listen():
        content = msg['data'].decode('utf8')
        yield 'data: {}\n\n'.format(content)

''' GEO '''

@app.route("/_getTopCoord")
def getTopCoord():
    try:
        date = datetime.datetime.fromtimestamp(float(request.args.get('date')))
    except:
        date = datetime.datetime.now()
    keyCateg = "GEO_COORD"
    topNum = 6 # default Num
    data = getZrange(keyCateg, date, topNum)
    return jsonify(data)

@app.route("/_getHitMap")
def getHitMap():
    try:
        date = datetime.datetime.fromtimestamp(float(request.args.get('date')))
    except:
        date = datetime.datetime.now()
    keyCateg = "GEO_COUNTRY"
    topNum = 0 # all
    data = getZrange(keyCateg, date, topNum)
    return jsonify(data)

def isCloseTo(coord1, coord2):
    clusterMeter = cfg.getfloat('GEO' ,'clusteringDistance')
    clusterThres = math.pow(10, len(str(abs(clusterMeter)))-7) #map meter to coord threshold (~ big approx)
    if abs(float(coord1[0]) - float(coord2[0])) <= clusterThres:
        if abs(float(coord1[1]) - float(coord2[1])) <= clusterThres:
            return True
    return False

@app.route("/_getCoordsByRadius")
def getCoordsByRadius():
    dico_coord = {}
    to_return = []
    try:
        dateStart = datetime.datetime.fromtimestamp(float(request.args.get('dateStart')))
        dateEnd = datetime.datetime.fromtimestamp(float(request.args.get('dateEnd')))
        centerLat = request.args.get('centerLat')
        centerLon = request.args.get('centerLon')
        radius = int(math.ceil(float(request.args.get('radius'))))
    except:
        return jsonify(to_return)

    delta = dateEnd - dateStart
    for i in range(delta.days+1):
        correctDatetime = dateStart + datetime.timedelta(days=i)
        date_str = util.getDateStrFormat(correctDatetime)
        keyCateg = 'GEO_RAD'
        keyname = "{}:{}".format(keyCateg, date_str)
        res = serv_redis_db.georadius(keyname, centerLon, centerLat, radius, unit='km', withcoord=True)

        #sum up really close coord
        for data, coord in res:
            flag_added = False
            coord = [coord[0], coord[1]]
            #list all coord
            for dicoCoordStr in dico_coord.keys():
                dicoCoord = json.loads(dicoCoordStr)
                #if curCoord close to coord
                if isCloseTo(dicoCoord, coord):
                    #add data to dico coord
                    dico_coord[dicoCoordStr].append(data)
                    flag_added = True
                    break
            # coord not in dic
            if not flag_added:
                dico_coord[str(coord)] = [data]

        for dicoCoord, array in dico_coord.items():
            dicoCoord = json.loads(dicoCoord)
            to_return.append([array, dicoCoord])

    return jsonify(to_return)

''' CONTRIB '''

@app.route("/_getLastContributors")
def getLastContributors():
    return jsonify(contributor_helper.getLastContributorsFromRedis())

@app.route("/_eventStreamLastContributor")
def getLastContributor():
    return Response(eventStreamLastContributor(), mimetype="text/event-stream")

@app.route("/_eventStreamAwards")
def getLastStreamAwards():
    return Response(eventStreamAwards(), mimetype="text/event-stream")

def eventStreamLastContributor():
    for msg in subscriber_lastContrib.listen():
        content = msg['data'].decode('utf8')
        contentJson = json.loads(content)
        lastContribJson = json.loads(contentJson['log'])
        org = lastContribJson['org']
        to_return = contributor_helper.getContributorFromRedis(org)
        epoch = lastContribJson['epoch']
        to_return['epoch'] = epoch
        yield 'data: {}\n\n'.format(json.dumps(to_return))

def eventStreamAwards():
    for msg in subscriber_lastAwards.listen():
        content = msg['data'].decode('utf8')
        contentJson = json.loads(content)
        data = json.loads(contentJson['data'])
        org = data['org']
        to_return = contributor_helper.getContributorFromRedis(org)
        epoch = data['epoch']
        to_return['epoch'] = epoch
        to_return['award'] = data['award']
        yield 'data: {}\n\n'.format(json.dumps(to_return))

@app.route("/_getTopContributor")
def getTopContributor(suppliedDate=None):
    if suppliedDate is None:
        try:
            date = datetime.datetime.fromtimestamp(float(request.args.get('date')))
        except:
            date = datetime.datetime.now()
    else:
        date = suppliedDate

    data = contributor_helper.getTopContributorFromRedis(date)
    return jsonify(data)

@app.route("/_getFameContributor")
def getFameContributor():
    try:
        date = datetime.datetime.fromtimestamp(float(request.args.get('date')))
    except:
        today = datetime.datetime.now()
        # get previous month
        date = (datetime.datetime(today.year, today.month, 1) - datetime.timedelta(days=1))
    return getTopContributor(suppliedDate=date)


@app.route("/_getTop5Overtime")
def getTop5Overtime():
    return jsonify(contributor_helper.getTop5OvertimeFromRedis())

@app.route("/_getOrgOvertime")
def getOrgOvertime():
    try:
        org = request.args.get('org')
    except:
        org = ''
    return jsonify(contributor_helper.getOrgOvertime(org))

@app.route("/_getCategPerContrib")
def getCategPerContrib():
    try:
        date = datetime.datetime.fromtimestamp(float(request.args.get('date')))
    except:
        date = datetime.datetime.now()

    return jsonify(contributor_helper.getCategPerContribFromRedis(date))

@app.route("/_getLatestAwards")
def getLatestAwards():
    try:
        date = datetime.datetime.fromtimestamp(float(request.args.get('date')))
    except:
        date = datetime.datetime.now()

    return jsonify(contributor_helper.getLastAwardsFromRedis())

@app.route("/_getAllOrg")
def getAllOrg():
    return jsonify(contributor_helper.getAllOrgFromRedis())

@app.route("/_getOrgRank")
def getOrgRank():
    try:
        org = request.args.get('org')
    except:
        org = ''
    return jsonify(contributor_helper.getCurrentOrgRankFromRedis(org))

@app.route("/_getContributionOrgStatus")
def getContributionOrgStatus():
    try:
        org = request.args.get('org')
    except:
        org = ''
    return jsonify(contributor_helper.getCurrentContributionStatus(org))

@app.route("/_getHonorBadges")
def getHonorBadges():
    try:
        org = request.args.get('org')
    except:
        org = ''
    return jsonify(contributor_helper.getOrgHonorBadges(org))

@app.route("/_getTrophies")
def getTrophies():
    try:
        org = request.args.get('org')
    except:
        org = ''
    return jsonify(contributor_helper.getOrgTrophies(org))

if __name__ == '__main__':
    app.run(host='localhost', port=8001, threaded=True)
