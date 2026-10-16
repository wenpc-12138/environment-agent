# -*- coding: utf-8 -*-
"""生态Agent - 演示知识库种子数据(首次启动时注入,便于无密钥体验)"""
import db

DEMO_ENTRIES = [
    {
        "title": "GB 13223-2011 火电厂大气污染物排放标准(2014年修改单)",
        "url": "https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/dqhjbh/dqgdwrywrwpbz/",
        "category": "standard",
        "source": "生态环境部",
        "content": "GB 13223-2011《火电厂大气污染物排放标准》适用于燃煤、燃油、燃气火电厂锅炉。重点区域燃煤锅炉 SO2 排放限值 50 mg/m3,NOx 100 mg/m3,烟尘 20 mg/m3(2014年第54号公告修改)。",
    },
    {
        "title": "GB 3095-2012 环境空气质量标准",
        "url": "https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/dqhjbh/dqhjzlbz/",
        "category": "standard",
        "source": "生态环境部",
        "content": "GB 3095-2012《环境空气质量标准》:PM2.5 年均一级 15 ug/m3、二级 35 ug/m3;24小时平均一级 35、二级 75 ug/m3。PM10 年均二级 70 ug/m3。SO2 年均二级 60 ug/m3,24小时二级 150 ug/m3。NO2 年均二级 40 ug/m3,24小时二级 80 ug/m3。",
    },
    {
        "title": "GB 3838-2002 地表水环境质量标准",
        "url": "https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/shjbh/shjzlbz/",
        "category": "standard",
        "source": "生态环境部",
        "content": "GB 3838-2002《地表水环境质量标准》:Ⅲ类水 COD ≤ 20 mg/L,氨氮 ≤ 1.0 mg/L,总磷(湖库)≤ 0.05 mg/L。Ⅰ类 COD ≤ 15,Ⅱ类 ≤ 15,Ⅳ类 ≤ 30,Ⅴ类 ≤ 40。",
    },
    {
        "title": "GB 12348-2008 工业企业厂界环境噪声排放标准",
        "url": "https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/wrfzjszc/stdwrzbzw/",
        "category": "standard",
        "source": "生态环境部",
        "content": "GB 12348-2008《工业企业厂界环境噪声排放标准》:厂界外声环境功能区 1 类昼间 55 dB(A)、夜间 45;2 类昼间 60、夜间 50;3 类昼间 65、夜间 55;4 类昼间 70、夜间 55。",
    },
    {
        "title": "HJ 75-2017 固定污染源烟气排放连续监测技术规范",
        "url": "https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/jcffbz/",
        "category": "standard",
        "source": "生态环境部",
        "content": "HJ 75-2017《固定污染源烟气(SO2、NOX、颗粒物)排放连续监测技术规范》:规定了 CEMS 安装、调试、验收、运行维护与数据有效性判定要求。数据有效率不低于 90%,有效数据小时均值参与达标判定。",
    },
    {
        "title": "HJ 836-2017 固定污染源废气 低浓度颗粒物测定 重量法",
        "url": "https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/jcffbz/",
        "category": "standard",
        "source": "生态环境部",
        "content": "HJ 836-2017《固定污染源废气 低浓度颗粒物的测定 重量法》:适用于排放浓度小于等于 50 mg/m3 的颗粒物测定,检出限 1.0 mg/m3。滤膜采样后恒重称量。",
    },
    {
        "title": "生态环境部关于火电、钢铁等行业超低排放改造政策(2023)",
        "url": "https://www.mee.gov.cn/",
        "category": "policy",
        "source": "生态环境部",
        "content": "《关于推进实施水泥行业超低排放的意见》(2024):水泥窑及窑尾余热利用系统烟气颗粒物、SO2、NOx 排放浓度小时均值分别不高于 10、35、50 mg/m3。",
    },
    {
        "title": "排污许可管理条例(国务院令第736号)",
        "url": "https://www.gov.cn/zhengce/content/2021-01/29/content_5583251.htm",
        "category": "policy",
        "source": "中国政府网",
        "content": "《排污许可管理条例》自 2021年3月1日起施行。排污单位应当依法申领排污许可证,按证排污。排污许可证内容包括许可排放浓度、许可排放量、自行监测要求等。",
    },
    {
        "title": "HJ 2.2-2018 环境影响评价技术导则 大气环境",
        "url": "https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/other/hjbhgc/",
        "category": "standard",
        "source": "生态环境部",
        "content": "HJ 2.2-2018《环境影响评价技术导则 大气环境》:规定了大气环境影响评价的工作程序、评价等级划分(一级/二级/三级)、预测模式选择(AERMOD、CALPUFF)、评价内容与结论要求。",
    },
    {
        "title": "环境监测机构资质认定与质量保证要点",
        "url": "",
        "category": "network",
        "source": "行业交流资料",
        "content": "环境监测机构应通过检验检测机构资质认定(CMA)。质量保证要点:仪器检定/校准在有效期内、采样空白与平行样比例不低于 10%、质控样回收率在允许范围、监测报告三级审核。",
    },
]


def seed_if_empty():
    n = db.q("SELECT COUNT(*) c FROM kb_entries", one=True)["c"]
    if n > 0:
        return False
    for e in DEMO_ENTRIES:
        db.kb_add(e["title"], e["url"], e["category"], e["content"], e["source"])
    return True
