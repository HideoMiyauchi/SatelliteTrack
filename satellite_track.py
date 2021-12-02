# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
from pytz import timezone
from skyfield.api import load, Topos, EarthSatellite
import copy
import itertools
import maidenhead as mh
import re

# 人工衛星(satellite.txt)のデータを読み込む
satellites = []
with open('./satellite.txt') as f:
    for line_with_cr in f:
        line = line_with_cr.rstrip('\n')
        result = re.match('(.+),([0-9.]+)', line)
        if (result is not None):
            name = result.group(1)
            freq = float(result.group(2))
            satellites.append([name, freq])

# 観測地(websdr.txt)のデータを読み込む
observatories = []
with open('./websdr.txt') as f:
    index = 0
    freq_pairs = []
    for line_with_cr in f:
        line = line_with_cr.rstrip('\n')

        if ('------------' in line):
            if (index > 4):
                observatories.append([name, url, latlon, copy.deepcopy(freq_pairs)])
            freq_pairs.clear()
            index = 0
        elif (index == 1):
            name = line
        elif (index == 2):
            url = line
        elif (index == 3):
            latlon = mh.to_location(line) # grid square locator to longitude-latitude
        elif (index >= 4):
            result = re.match('([-0-9.]+) - ([0-9.]+) MHz', line)
            if (result is not None):
                start_freq = float(result.group(1))
                end_freq = float(result.group(2))
                freq_pairs.append([start_freq, end_freq])
        index = index + 1

# NORAD TLEデータのリスト
tle_urls = [
    'http://celestrak.com/NORAD/elements/amateur.txt',
    'http://celestrak.com/NORAD/elements/cubesat.txt',
    'http://celestrak.com/NORAD/elements/weather.txt',
    'http://celestrak.com/NORAD/elements/stations.txt'
]

# 天体歴を得る
eph = load('de421.bsp') # ephemeris DE421
sun, earth = eph['sun'], eph['earth']

# 観測時刻を決める
tz = timezone('Asia/Tokyo')
ts = load.timescale()
t0 = ts.now()
t1 = ts.utc(t0.utc_datetime() + timedelta(hours=8))

# NORADからTLEデータをダウンロードする
tle_data = {}
for tle_url in tle_urls:
    tle_data.update(load.tle(tle_url))

# 人工衛星のビーコン周波数を受信できる観測地を調べる
iter = []
for satellite in satellites:
    satellite_freq = satellite[1]
    for observatory in observatories:
        for freq_pair in observatory[3]:
            if (satellite_freq >= freq_pair[0] and satellite_freq <= freq_pair[1]):
                iter.append([satellite, observatory])
                break

# 観測地での人工衛星のイベントを調べる
choiced_event_list = []
for satellite, observatory in iter:

    # 観測地の緯度・経度を得る (標高は不明なので10mとした)
    latlon = observatory[2]
    observatory_latlon = Topos(latlon[0], latlon[1], elevation_m = 10)

    # 人工衛星のTLEデータを得る
    satellite_tle_data = tle_data.get(satellite[0])

    # 人工衛星が指定時刻間(t0-t1) に観測地の40度以上の上空を通るイベントを見つける
    ts, events = satellite_tle_data.find_events(observatory_latlon, t0, t1, altitude_degrees = 40.0)

    # 上空を通るイベントで条件を満たすものだけを抽出する
    event_list = []
    event_type = 0
    for t, event in zip(ts, events):

        # イベント種別 (0:見え始め,1:最高高度,2:見え終り)
        if (event == event_type):

            # イベント時刻
            event_list.append(t.utc_datetime()) # event_list[0|6|12]

            # イベントの高度・方位角・距離を求める
            altitude, azimuth, distance = (satellite_tle_data - observatory_latlon).at(t).altaz()
            event_list.append(altitude.degrees) # event_list[1|7|13]
            event_list.append(azimuth.degrees)  # event_list[2|8|14]
            event_list.append(distance.km)      # event_list[3|9|15]

            # 人工衛星に陽が当たっているか
            sun_light = satellite_tle_data.at(t).is_sunlit(eph)
            event_list.append(sun_light)        # event_list[4|10|16]

            # 太陽の高度
            sun_altitude = (earth + observatory_latlon).at(t).observe(sun).apparent().altaz()[0]
            event_list.append(sun_altitude.degrees) # event_list[5|11|17]

            # 次の条件を満たすイベントのみ抽出する
            if (event == 2):
                # 最高高度が80度以上
                # 人工衛星が常に陽に照らされている
                # 太陽高度が10度以上
                if (event_list[7] >= 80 and
                    event_list[4] == True and event_list[10] == True and event_list[16] == True and
                    event_list[5] >= 10 and event_list[11] >= 10 and event_list[17] >= 10):
                    event_list.append(satellite[0])   # event_list[18]
                    event_list.append(satellite[1])   # event_list[19]
                    event_list.append(observatory[0]) # event_list[20]
                    event_list.append(observatory[1]) # event_list[21]
                    event_list.append(observatory[2]) # event_list[22]
                    choiced_event_list.append(copy.deepcopy(event_list))
                event_type = 0
                event_list.clear()
            else:
                event_type = event_type + 1
        else:
            event_type = 0
            event_list.clear()

# 見え始め時刻でソートする
sorted_event_list = sorted(choiced_event_list, key=lambda x:(x[0]))

# 結果を文字列に変換する
for event_list in sorted_event_list:

    satellite_name, satellite_freq, observatory_name, observatory_url, observatory_latlon = event_list[18:23]
    print("----------------------")
    print(satellite_name + ", " + str(satellite_freq) + "MHz")
    print(observatory_name)
    print(observatory_url)

    def to_format(list_parts):
        t, alt, az, distance = list_parts
        print(t.astimezone(tz).strftime("%y/%m/%d %H:%M:%S") +
            ", {0:.1f}, {1:.1f}, {2:.1f}".format(alt, az, distance))

    to_format(event_list[0:4])
    to_format(event_list[6:10])
    to_format(event_list[12:16])

# ----- end of program -----
