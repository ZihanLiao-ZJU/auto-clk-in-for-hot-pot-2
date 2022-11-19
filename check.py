#! /usr/bin/env python
# -*- coding: utf-8 -*-
# __author__ = "zihan"
# Date: 2022/9/14
import requests
import re
import json
import datetime
import time
import os
import random
from notify.tgpush import post_tg
from notify.Dingpush import dingpush

#签到程序模块
class LoginError(Exception):
    """Login Exception"""
    pass


def get_day(delta=0):
    """
    获得指定格式的日期
    """
    today = datetime.date.today()
    oneday = datetime.timedelta(days=delta)
    yesterday = today - oneday
    return yesterday.strftime("%Y%m%d")


def take_out_json(content):
    """
    从字符串jsonp中提取json数据
    """
    s = re.search("^jsonp_\d+_\((.*?)\);?$", content)
    return json.loads(s.group(1) if s else "{}")


def get_date():
    """Get current date"""
    today = datetime.date.today()
    return "%4d%02d%02d" % (today.year, today.month, today.day)


class ZJULogin(object):
    """
    Attributes:
        username: (str) 浙大统一认证平台用户名（一般为学号）
        password: (str) 浙大统一认证平台密码
        sess: (requests.Session) 统一的session管理
    """

    def __init__(self,username,password,DD_BOT_TOKEN,DD_BOT_SECRET,reminders,lng,lat,delay_run):
        self.username = username
        self.password = password
        self.DD_BOT_TOKEN = DD_BOT_TOKEN
        self.DD_BOT_SECRET= DD_BOT_SECRET #哈希算法验证(可选)
        self.reminders = reminders
        self.lng= lng # 经度
        self.lat= lat # 维度
        self.delay_run = delay_run
        self.sess = requests.Session()
        self.imgaddress = 'https://healthreport.zju.edu.cn/ncov/wap/default/code'
        self.BASE_URL = "https://healthreport.zju.edu.cn/ncov/wap/default/index"
        self.LOGIN_URL = "https://zjuam.zju.edu.cn/cas/login?service=http%3A%2F%2Fservice.zju.edu.cn%2F"
        self.headers = {
            'user-agent': 'Mozilla/5.0 (Linux; U; Android 11; zh-CN; M2012K11AC Build/RKQ1.200826.002) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/69.0.3497.100 UWS/3.22.0.36 Mobile Safari/537.36 AliApp(DingTalk/6.0.7.1) com.alibaba.android.rimet.zju/14785964 Channel/1543545060864 language/zh-CN 2ndType/exclusive UT4Aplus/0.2.25 colorScheme/light',
        }
        self.REDIRECT_URL = "https://zjuam.zju.edu.cn/cas/login?service=https%3A%2F%2Fhealthreport.zju.edu.cn%2Fa_zju%2Fapi%2Fsso%2Findex%3Fredirect%3Dhttps%253A%252F%252Fhealthreport.zju.edu.cn%252Fncov%252Fwap%252Fdefault%252Findex%26from%3Dwap"

    def login(self):
        """Login to ZJU platform"""
        res = self.sess.get(self.LOGIN_URL)
        execution = re.search(
            'name="execution" value="(.*?)"', res.text).group(1)
        res = self.sess.get(
            url='https://zjuam.zju.edu.cn/cas/v2/getPubKey').json()
        n, e = res['modulus'], res['exponent']
        encrypt_password = self._rsa_encrypt(self.password, e, n)

        data = {
            'username': self.username,
            'password': encrypt_password,
            'execution': execution,
            '_eventId': 'submit',
            "authcode": ""
        }
        res = self.sess.post(url=self.LOGIN_URL, data=data)
        # check if login successfully
        if '用户名或密码错误' in res.content.decode():
            raise LoginError('登录失败，请核实账号密码重新登录')
        print("统一认证平台登录成功")
        return self.sess

    def _rsa_encrypt(self, password_str, e_str, M_str):
        password_bytes = bytes(password_str, 'ascii')
        password_int = int.from_bytes(password_bytes, 'big')
        e_int = int(e_str, 16)
        M_int = int(M_str, 16)
        result_int = pow(password_int, e_int, M_int)
        return hex(result_int)[2:].rjust(128, '0')


class HealthCheckInHelper(ZJULogin):

    def get_geo_info(self, location: dict):
        params = (
            ('key', '729923f88542d91590470f613adb27b5'),
            ('s', 'rsv3'),
            ('language', 'zh_cn'),
            ('location', '{lng},{lat}'.format(lng=location.get("lng"), lat=location.get("lat"))),
            ('extensions', 'base'),
            ('callback', 'jsonp_607701_'),
            ('platform', 'JS'),
            ('logversion', '2.0'),
            ('appname', 'https://healthreport.zju.edu.cn/ncov/wap/default/index'),
            ('csid', '63157A4E-D820-44E1-B032-A77418183A4C'),
            ('sdkversion', '1.4.16'),
        )

        response = self.sess.get('https://restapi.amap.com/v3/geocode/regeo', headers=self.headers, params=params)
        return take_out_json(response.text)

    def take_in(self, geo_info: dict):
        formatted_address = geo_info.get("regeocode").get("formatted_address")
        address_component = geo_info.get("regeocode").get("addressComponent")
        if not formatted_address or not address_component: return

        # 获得id和uid参数
        time.sleep(3)
        res = self.sess.get(self.BASE_URL, headers=self.headers)
        print(len(res.content))
        if len(res.content) == 0:
            print('网页获取失败，请检查网络并重试')
            self.Push('网页获取失败，请检查网络并重试')
        html = res.content.decode()
        try:
            re.findall('温馨提示： 不外出、不聚集、不吃野味， 戴口罩、勤洗手、咳嗽有礼，开窗通风，发热就诊',html)[0]
            print('打卡网页获取成功')
        except:
            print('打卡网页获取失败')
            self.Push('打卡网页获取失败')
        finally:
            new_info_tmp = json.loads(re.findall(r'def = ({[^\n]+})', html)[0])
            new_id = new_info_tmp['id']
            new_uid = new_info_tmp['uid']
            # 拼凑geo信息
            lng, lat = address_component.get("streetNumber").get("location").split(",")
            geo_api_info_dict = {"type": "complete", "info": "SUCCESS", "status": 1,
                                 "position": {"Q": lat, "R": lng, "lng": lng, "lat": lat},
                                 "message": "Get geolocation success.Convert Success.Get address success.", "location_type": "ip",
                                 "accuracy": "null", "isConverted": "true", "addressComponent": address_component,
                                 "formattedAddress": formatted_address, "roads": [], "crosses": [], "pois": []}
            print('打卡地点：', formatted_address)
            data = {
                'sfymqjczrj': '0',
                'zjdfgj': '',
                'sfyrjjh': '0',
                'cfgj': '',
                'tjgj': '',
                'nrjrq': '0',
                'rjka': '',
                'jnmddsheng': '',
                'jnmddshi': '',
                'jnmddqu': '',
                'jnmddxiangxi': '',
                'rjjtfs': '',
                'rjjtfs1': '',
                'rjjtgjbc': '',
                'jnjtfs': '',
                'jnjtfs1': '',
                'jnjtgjbc': '',
                'sfqrxxss': '1', # 本人承诺：上述信息属实 (是:1,否:0)
                'sfqtyyqjwdg': '',
                'sffrqjwdg': '',
                'sfhsjc': '',
                'zgfx14rfh': '0',
                'zgfx14rfhdd': '',
                'sfyxjzxgym': '',
                'sfbyjzrq': '0', # 是否不宜接种人群
                'jzxgymqk': '0', # 这里是第三针相关参数[已删除]
                'tw': '0', # 今日是否有发热症状（高于37.2 ℃）(是:1,否:0)
                'sfcxtz': '0',
                'sfjcbh': '0', # 是否有与新冠疫情确诊人员或密接人员有接触的情况? (是:1,否:0)
                'sfcxzysx': '0', # 今日是否有涉及涉疫情的管控措施 (是:1,否:0)
                'jcjg': '',
                'qksm': '',
                'sfyyjc': '0',
                'jcjgqr': '0',
                'remark': '',
                'address': formatted_address,
                # {"type":"complete","position":{"Q":30.30975640191,"R":120.085647515191,"lng":120.085648,"lat":30.309756},"location_type":"html5","message":"Get geolocation success.Convert Success.Get address success.","accuracy":40,"isConverted":true,"status":1,"addressComponent":{"citycode":"0571","adcode":"330106","businessAreas":[],"neighborhoodType":"","neighborhood":"","building":"","buildingType":"","street":"龙宇街","streetNumber":"17-18号","country":"中国","province":"浙江省","city":"杭州市","district":"西湖区","towncode":"330106109000","township":"三墩镇"},"formattedAddress":"浙江省杭州市西湖区三墩镇翠柏浙江大学(紫金港校区)","roads":[],"crosses":[],"pois":[],"info":"SUCCESS"}
                'geo_api_info': geo_api_info_dict,
                # 浙江省 杭州市 西湖区
                # '\u6D59\u6C5F\u7701 \u676D\u5DDE\u5E02 \u897F\u6E56\u533A'
                'area': "{} {} {}".format(address_component.get("province"), address_component.get("city"),
                                          address_component.get("district")),
                # 浙江省
                # '\u6D59\u6C5F\u7701'
                'province': address_component.get("province"),
                # 杭州市
                # '\u676D\u5DDE\u5E02'
                'city': address_component.get("city"),
                'sfzx': '1', # 今日是否在校 (在校:1,不在:0)
                'sfjcwhry': '0',
                'sfjchbry': '0',
                'sfcyglq': '0',
                'gllx': '',
                'glksrq': '',
                'jcbhlx': '',
                'jcbhrq': '',
                'bztcyy': '',
                'sftjhb': '',
                'sftjwh': '0',
                'sfjcqz': '',
                'jcqzrq': '',
                'jrsfqzys': '',
                'jrsfqzfy': '',
                'sfyqjzgc': '0',
                'sfsqhzjkk': '0', # 是否申领杭州健康码
                'sqhzjkkys': '1', # 今日申领健康码状态(绿色:1,红色:2,黄色:3,橙色:4,无:5)
                'gwszgzcs': '',
                'szgj': '',
                'fxyy': '',
                'jcjg': '',
                # uid每个用户不一致
                'uid': new_uid,
                # id每个用户不一致
                'id': new_id,
                # 日期
                'date': get_date(),
                'created': round(time.time()),
                'szsqsfybl': '0',
                'sfygtjzzfj': '0',
                'gtjzzfjsj': '',
                'gwszdd': '',
                'szgjcs': '',
                'ismoved': '0',
                'zgfx14rfhsj':'',
                'campus': '海宁校区', # 所在校区(紫金港校区 玉泉校区 西溪校区 华家池校区 之江校区 海宁校区 舟山校区 宁波校区 工程师学院 杭州国际科创中心 其他)
                # 👇-----2022.5.19日修改-----👇
                'verifyCode': ''  ,
                # 👆-----2022.5.19日修改-----👆
                'internship': '1' # 今日是否进行实习或实践(校内实习:2,校外实习:3,否:1)
            }
            response = self.sess.post('https://healthreport.zju.edu.cn/ncov/wap/default/save', data=data,
                                      headers=self.headers)
            return response.json()

    def Push(self,res):
        if res:
            if self.DD_BOT_TOKEN:
                ding= dingpush('{}浙江大学每日健康打卡'.format(self.username), res,self.reminders,self.DD_BOT_TOKEN,self.DD_BOT_SECRET)
                ding.SelectAndPush()
            else:
                print("钉钉推送未配置，请自行查看签到结果")
            print("推送完成！")

    def run(self):
        print("正在为{}健康打卡".format(self.username))
        if self.delay_run:
            # 确保定时脚本执行时间不太一致
            time.sleep(random.randint(10, 100))
        try:
            self.login()
            # 拿取eai-sess的cookies信息
            self.sess.get(self.REDIRECT_URL)
            location = {'info': 'LOCATE_SUCCESS', 'status': 1, 'lng': self.lng, 'lat': self.lat}
            geo_info = self.get_geo_info(location)
            res = self.take_in(geo_info)
            print(res)
            self.Push(res)
        except requests.exceptions.ConnectionError :
            # reraise as KubeException, but log stacktrace.
            print("打卡失败,请检查github服务器网络状态")
            self.Push('打卡失败,请检查github服务器网络状态')

if __name__ == '__main__':
    DD_BOT_TOKEN = os.getenv("DD_BOT_TOKEN")
    DD_BOT_SECRET=os.getenv("DD_BOT_SECRET") #哈希算法验证(可选)
    reminders = os.getenv("REMINDERS")
    lng= os.getenv("lng") # 经度
    lat= os.getenv("lat") # 维度
    user = [0]
    Nuser = len(user)
    for iuser in range(Nuser):
        username = os.getenv("account{}".format(user[iuser]))
        password = os.getenv("password{}".format(user[iuser]))
        s = HealthCheckInHelper(username,password,DD_BOT_TOKEN,DD_BOT_SECRET,reminders,lng,lat,delay_run=False)
        s.run()
    
