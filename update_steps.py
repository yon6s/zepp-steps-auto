#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Zepp Life (原小米运动) -> 微信运动 步数同步修改工具 (双通道云端自动化版)
- 通道 1 (默认优先): 虚拟设备网关通道
- 通道 2 (直连备用): 华米官方 API v2 AES 加密直连通道 + 直连步数提交
"""

import argparse
import datetime
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))

# 试运行截止日期 (含当日, 北京时间): 2026-10-27 至 2026-11-02 共 7 天
EXPIRY_DATE = os.environ.get("EXPIRY_DATE", "2026-11-02")


def get_beijing_now() -> datetime.datetime:
    return datetime.datetime.now(BEIJING_TZ)


def aes_cbc_encrypt(plaintext_bytes: bytes, key_bytes: bytes, iv_bytes: bytes, base64_out: bool = False) -> bytes:
    cmd = ["openssl", "enc", "-aes-128-cbc", "-K", key_bytes.hex(), "-iv", iv_bytes.hex()]
    if base64_out:
        cmd.extend(["-base64", "-A"])
    proc = subprocess.run(cmd, input=plaintext_bytes, capture_output=True, check=True)
    return proc.stdout


def update_via_gateway(account: str, password: str, steps: int) -> bool:
    """通道 1: 通过虚拟设备网关提交步数"""
    try:
        payload = json.dumps({
            "ups1": account,
            "ups2": password,
            "ups3": str(steps),
            "timestamp": int(time.time() * 1000),
        }).encode("utf-8")

        encrypted_b64 = aes_cbc_encrypt(
            payload,
            b"Yx9#mK2$pL7@qN4^",
            b"Bw5&hT8!vR3%jM6*",
            base64_out=True,
        ).decode("utf-8").strip()

        data = urllib.parse.urlencode({"encrypted": encrypted_b64}).encode("utf-8")
        req = urllib.request.Request(
            "https://bs.yanwan.store/run4/mi20251001.php",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://bs.yanwan.store",
                "Referer": "https://bs.yanwan.store/run4/",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
                "X-Requested-With": "XMLHttpRequest",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
        res = json.loads(body)
        print(f"📡 [通道1-网关] 响应: {res}")
        if res.get("code") == 200:
            print(f"🎉 [通道1-网关] 步数已成功修改为: {steps} 步！")
            return True
    except Exception as e:
        print(f"⚠️ [通道1-网关] 请求异常，切换通道2直连: {e}")
    return False


def update_via_direct_huami(account: str, password: str, steps: int) -> bool:
    """通道 2: 华米官方 API v2 AES 加密直连通道"""
    try:
        login_data = {
            "emailOrPhone": account,
            "password": password,
            "state": "REDIRECTION",
            "client_id": "HuaMi",
            "country_code": "CN",
            "token": "access",
            "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
        }
        query = urllib.parse.urlencode(login_data).encode("utf-8")
        cipher_data = aes_cbc_encrypt(query, b"xeNtBVqzDc6tuNTh", b"MAAAYAAAAAAAAABg", base64_out=False)

        headers1 = {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "user-agent": "MiFit6.14.0 (M2007J1SC; Android 12; Density/2.75)",
            "app_name": "com.xiaomi.hm.health",
            "appname": "com.xiaomi.hm.health",
            "appplatform": "android_phone",
            "x-hm-ekv": "1",
            "hm-privacy-ceip": "false",
        }

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        req1 = urllib.request.Request(
            "https://api-user.zepp.com/v2/registrations/tokens",
            data=cipher_data,
            headers=headers1,
            method="POST",
        )
        code = None
        try:
            opener.open(req1, timeout=15)
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location", "")
            matches = re.findall(r"(?<=access=).*?(?=&)", loc)
            if matches:
                code = matches[0]

        if not code:
            print("❌ [通道2-直连] 未能获取到 access code")
            return False

        is_phone = bool(re.match(r"^\+?\d+$", account))
        headers2 = {
            "app_name": "com.xiaomi.hm.health",
            "x-request-id": str(uuid.uuid4()),
            "accept-language": "zh-CN",
            "appname": "com.xiaomi.hm.health",
            "cv": "50818_6.14.0",
            "v": "2.0",
            "appplatform": "android_phone",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "user-agent": "MiFit6.14.0 (M2007J1SC; Android 12; Density/2.75)",
        }
        data2 = urllib.parse.urlencode({
            "allow_registration=": "false",
            "app_name": "com.xiaomi.hm.health",
            "app_version": "6.14.0",
            "code": code,
            "country_code": "CN",
            "device_id": "DA932FFFFE8816E7",
            "device_model": "android_phone",
            "dn": "account.zepp.com,api-user.zepp.com,api-mifit.zepp.com,api-watch.zepp.com,app-analytics.zepp.com,api-analytics.huami.com,auth.zepp.com",
            "grant_type": "access_token",
            "lang": "zh_CN",
            "os_version": "1.5.0",
            "source": "com.xiaomi.hm.health:6.14.0:50818",
            "third_name": "huami_phone" if is_phone else "email",
        }).encode("utf-8")

        req2 = urllib.request.Request("https://account.huami.com/v2/client/login", data=data2, headers=headers2, method="POST")
        with urllib.request.urlopen(req2, timeout=15) as resp2:
            res2 = json.loads(resp2.read().decode("utf-8"))

        app_token = res2["token_info"]["app_token"]
        user_id = res2["token_info"]["user_id"]

        sec_ts = int(time.time())
        date_today = get_beijing_now().strftime("%Y-%m-%d")
        device_id = "DA932FFFFE8816E7"

        data_json = (
            "%5b%7b%22data_hr%22%3a%22"
            + "%5c%2fv7%2b" * 480
            + f"%22%2c%22date%22%3a%22{date_today}%22%2c%22data%22%3a%5b%7b%22start%22%3a0%2c%22stop%22%3a1439%2c%22value%22%3a%22"
            + "A" * 5760
            + f"%22%2c%22tz%22%3a32%2c%22did%22%3a%22{device_id}%22%2c%22src%22%3a24%7d%5d%2c%22summary%22%3a%22%7b%5c%22v%5c%22%3a6%2c%5c%22slp%5c%22%3a%7b%5c%22st%5c%22%3a0%2c%5c%22ed%5c%22%3a0%2c%5c%22dp%5c%22%3a0%2c%5c%22lt%5c%22%3a0%2c%5c%22wk%5c%22%3a0%2c%5c%22usrSt%5c%22%3a-1440%2c%5c%22usrEd%5c%22%3a-1440%2c%5c%22wc%5c%22%3a0%2c%5c%22is%5c%22%3a0%2c%5c%22lb%5c%22%3a0%2c%5c%22to%5c%22%3a0%2c%5c%22dt%5c%22%3a0%2c%5c%22rhr%5c%22%3a0%2c%5c%22ss%5c%22%3a0%7d%2c%5c%22stp%5c%22%3a%7b%5c%22ttl%5c%22%3a{steps}%2c%5c%22dis%5c%22%3a0%2c%5c%22cal%5c%22%3a0%2c%5c%22wk%5c%22%3a0%2c%5c%22rn%5c%22%3a0%2c%5c%22runDist%5c%22%3a0%2c%5c%22runCal%5c%22%3a0%2c%5c%22stage%5c%22%3a%5b%5d%7d%2c%5c%22goal%5c%22%3a8000%2c%5c%22tz%5c%22%3a%5c%2228800%5c%22%7d%22%2c%22source%22%3a24%2c%22type%22%3a0%7d%5d"
        )

        url0 = f"https://api-mifit-cn.huami.com/v1/data/band_data.json?&t={sec_ts}"
        data0 = f"userid={user_id}&last_sync_data_time={sec_ts}&device_type=0&last_deviceid={device_id}&data_json={data_json}"
        headers0 = {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "user-agent": "MiFit6.14.0 (M2007J1SC; Android 12; Density/2.75)",
            "app_name": "com.xiaomi.hm.health",
            "apptoken": app_token,
        }
        req0 = urllib.request.Request(url0, data=data0.encode("utf-8"), headers=headers0, method="POST")
        with urllib.request.urlopen(req0, timeout=15) as resp0:
            res0 = json.loads(resp0.read().decode("utf-8"))
        print(f"📡 [通道2-直连] 响应: {res0}")
        if res0.get("message") == "success":
            print(f"🎉 [通道2-直连] 步数已成功修改为: {steps} 步！")
            return True
    except Exception as e:
        print(f"❌ [通道2-直连] 异常: {e}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Zepp Life 微信步数修改工具")
    parser.add_argument("-a", "--account", default=os.environ.get("ZEPP_ACCOUNT"), help="Zepp Life 账号")
    parser.add_argument("-p", "--password", default=os.environ.get("ZEPP_PASSWORD"), help="Zepp Life 密码")
    parser.add_argument("-s", "--steps", type=int, default=None, help="固定目标步数")
    parser.add_argument("--min-steps", type=int, default=int(os.environ.get("MIN_STEPS", "12000")), help="随机最小步数")
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "15000")), help="随机最大步数")
    parser.add_argument("--ignore-expiry", action="store_true", help="忽略7天试运行截止日期限制")
    args = parser.parse_args()

    now_bj = get_beijing_now()
    today_str = now_bj.strftime("%Y-%m-%d")
    print(f"🕒 当前北京时间: {now_bj.strftime('%Y-%m-%d %H:%M:%S')}")

    if not args.ignore_expiry and EXPIRY_DATE and today_str > EXPIRY_DATE:
        print(f"⏹️ 7天试运行已于 {EXPIRY_DATE} 结束 (今日 {today_str})，自动跳过执行。")
        sys.exit(0)

    if not args.account or not args.password:
        print("⚠️ 请提供账号和密码！")
        sys.exit(1)

    steps = args.steps if args.steps else random.randint(args.min_steps, args.max_steps)
    steps = min(steps, 98800)

    print(f"🚀 开始同步步数: 范围=[{args.min_steps}, {args.max_steps}], 本次目标步数={steps}")
    if update_via_gateway(args.account, args.password, steps):
        sys.exit(0)
    if update_via_direct_huami(args.account, args.password, steps):
        sys.exit(0)

    print("❌ 双通道均未能完成同步，请检查日志。")
    sys.exit(1)


if __name__ == "__main__":
    main()
