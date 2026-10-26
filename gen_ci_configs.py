"""CI 每轮动态生成阶梯配置：锚点自动滚动到「明天起最早可订日」。

背景：预订窗口只开放到后天左右（实测 T+2），且逐日滚动。把入住锚点写死在
配置里会很快过期（查空），所以每轮运行时重新计算：

  anchor = min(日历上 >= 明天 的可订日)   （扫描全部驿站；失败回退 today+2）

然后写出 8 个阶梯配置（15/13/11/9/7/5/3/2 天档），配合 monitor.py 的
「时长制」指纹（stay:<N>d），锚点滚动不会触发重复推送，只有"从住不满
变住得满"才推。区域白名单见 ALLOWED_DISTRICTS（通勤 2h 内，排除崇明/
金山/临港）。

只依赖 requests；由 workflow 在每组 job 里先于 monitor.py 运行。
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

BASE_URL = "https://qnyz.shyouth.net/qnyzApi"
LADDER = [15, 13, 11, 9, 7, 5, 3, 2]          # 天档；与 workflow matrix 的组一一对应
LADDER_FILES = {15: "config.ci.a.yaml"}       # 其余档位文件名按天数生成
# 通勤 2 小时内白名单（排除崇明区/金山区/临港新片区；想调整直接改这里）
ALLOWED_DISTRICTS = [
    "黄浦区", "徐汇区", "长宁区", "静安区", "普陀区", "虹口区", "杨浦区",
    "浦东新区", "闵行区", "宝山区", "嘉定区", "松江区", "青浦区", "奉贤区",
]

TPL = """# 由 gen_ci_configs.py 每轮自动生成，手改会被覆盖（锚点会滚动）。
# 档位 {n} 天：{f} -> {t}（锚点=明天起最早可订日），仅个人，通勤 2h 内区域。
# 去重按"能住满 {n} 天"的时长计，锚点滚动不重推；想改档位/区域改 gen_ci_configs.py。

base_url: "{base}"
verify_ssl: false
check_availability: true
concurrency: 10

filters:
  name: ""
  user_type: 2
  apply_scope: "personal"
  districts: {districts}
  only_stations: []
  date_from: "{f}"
  date_to: "{t}"
  min_house_count: 0
  min_apply_number: 1
  max_commute_min: 90   # 到人民广场门到门通勤估算上限（超 1.5h 剔除；0=不限）

notify:
  type: "bark"
  url: ""

log_file: ""
"""


def earliest_bookable(tomorrow):
    """扫描全部驿站日历，返回 >= tomorrow 的最早可订日；失败返回 None。"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    sess = requests.Session()
    sess.verify = False
    sess.headers.update({"User-Agent": "Mozilla/5.0 (qnyz-monitor-gen)",
                         "Accept": "application/json, text/plain, */*"})
    r = sess.post(f"{BASE_URL}/hous/housListBatch", json={
        "name": "", "userType": 2, "housType": 1, "districts": [],
        "startTime": "", "endTime": "", "intoPerNum": ""}, timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 200:
        raise RuntimeError(f"housListBatch 失败: {body.get('msg')}")
    ids = [s.get("id") for s in (body.get("data") or [])]

    def first_open(hid):
        try:
            cr = sess.get(f"{BASE_URL}/hous/calendar", params={"id": hid}, timeout=30)
            for d in (cr.json().get("data") or []):
                try:
                    dd = date.fromisoformat(str(d.get("applyDate"))[:10])
                except (TypeError, ValueError):
                    continue
                if dd >= tomorrow and int(d.get("applyNumber") or 0) >= 1:
                    return dd
        except Exception:
            return None
        return None

    best = None
    with ThreadPoolExecutor(max_workers=10) as ex:
        for res in ex.map(first_open, ids):
            if res and (best is None or res < best):
                best = res
    return best


def main():
    tomorrow = date.today() + timedelta(days=1)
    anchor = earliest_bookable(tomorrow) or (date.today() + timedelta(days=2))
    print(f"锚点（明天 {tomorrow} 起最早可订日）= {anchor}")
    districts = repr(ALLOWED_DISTRICTS)
    for n in LADDER:
        end = anchor + timedelta(days=n - 1)
        path = LADDER_FILES.get(n, f"config.ci.d{n}.yaml")
        with open(path, "w") as fh:
            fh.write(TPL.format(n=n, f=anchor.isoformat(), t=end.isoformat(),
                                base=BASE_URL, districts=districts))
        print(f"  写 {path}: {anchor} -> {end}")
    # 供 workflow 日志观察
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as fh:
        fh.write(f"anchor={anchor}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
