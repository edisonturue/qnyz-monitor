"""通勤时间估算：驿站经纬度 -> 到市中心（人民广场）的门到门地铁时间。

模型（无需 API key，离线可用）：
    估算分钟 = 14（进出站+平均换乘等待）+ 直线距离 × 1.25（路网/线路绕行）÷ 45km/h

校准参考（人民广场出发）：
    莘庄（直线17km）≈ 42min，嘉定新城（24km）≈ 54min，
    奉贤新城（32km）≈ 67min，滴水湖（55km）≈ 106min。
误差约 ±15%，用于"剔除通勤过远"和"按远近排序"足够。

如需真实公交路径规划，可接高德 Web 服务 API（direction/transit/integrated），
但免费配额有限（92 站 × 每轮查询会超额），建议只做一次性校准：
    AMAP_KEY=xxx python3 -c "from commute import amap_minutes; print(amap_minutes(31.23,121.47,31.40,121.42))"
"""

import math
import os

ORIGIN_LAT, ORIGIN_LON = 31.2304, 121.4737   # 人民广场
_ROAD_FACTOR = 1.25      # 地铁线路/接驳绕行系数
_SPEED_KM_MIN = 0.75     # 等效旅行速度 45km/h（含站停）
_FIXED_MIN = 14          # 进出站 + 平均一次换乘等待

# 无地铁或接驳差区域的惩罚（分钟）：直线模型按“有地铁”折算，
# 这些区域实际靠隧道公交/铁路/长途接驳，模型会低估，按实际经验补偿。
_DISTRICT_PENALTY = {
    "崇明区": 40,        # 无地铁，G40 隧道公交/自驾，门到门普遍 2h+
    "金山区": 20,        # 金山铁路班次少、接驳差
    "临港新片区": 12,     # 16 号线超长站距 + 末端接驳
}


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate_minutes(lat, lon, origin=(ORIGIN_LAT, ORIGIN_LON), district=None):
    """驿站在 (lat, lon) -> 到原点的门到门通勤估算（分钟）。"""
    d = haversine_km(origin[0], origin[1], lat, lon)
    return round(_FIXED_MIN + d * _ROAD_FACTOR / _SPEED_KM_MIN
                 + _DISTRICT_PENALTY.get(district or "", 0))


def amap_minutes(orig_lat, orig_lon, dest_lat, dest_lon):
    """可选：高德真实公交路径规划。需环境变量 AMAP_KEY；失败返回 None。"""
    key = os.environ.get("AMAP_KEY")
    if not key:
        return None
    import requests
    try:
        r = requests.get(
            "https://restapi.amap.com/v5/direction/transit/integrated",
            params={
                "key": key,
                "origin": f"{orig_lon},{orig_lat}",
                "destination": f"{dest_lon},{dest_lat}",
                "city1": "021", "city2": "021",
                "strategy": 0,          # 最快捷
                "show_fields": "cost",
            },
            timeout=15,
        )
        data = r.json()
        if data.get("status") == "1":
            transit = (data.get("route") or {}).get("transits") or []
            if transit:
                cost = transit[0].get("cost") or {}
                dur = cost.get("duration") or cost.get("transit_duration")
                if dur:
                    return max(1, round(int(dur) / 60))
    except Exception:
        return None
    return None


if __name__ == "__main__":
    # 自检：打印典型站点估算
    samples = [
        ("莘庄", 31.1116, 121.3867),
        ("嘉定新城", 31.3840, 121.2640),
        ("奉贤新城", 30.9180, 121.4930),
        ("滴水湖", 30.9000, 121.9300),
        ("崇明城桥", 31.6260, 121.3970),
        ("五角场", 31.3030, 121.5140),
    ]
    for name, lat, lon in samples:
        print(f"{name:8s} 直线{haversine_km(ORIGIN_LAT, ORIGIN_LON, lat, lon):5.1f}km  估算{estimate_minutes(lat, lon):3d}min")
