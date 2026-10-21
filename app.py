import datetime
import itertools
import os
import math
import base64
from typing import Dict, List, Tuple, Any, Optional

import geonamescache
import pandas as pd
import pytz
import streamlit as st
import swisseph as swe
from timezonefinder import TimezoneFinder
import uuid

# ==================== 1. Security (Fixed) ====================
KEY_FILE = "license.key"

def get_machine_id():
    return hex(uuid.getnode())

def generate_password(mid):
    digits = ''.join(filter(str.isdigit, mid))
    num = int(digits[:8]) if digits else int(mid.encode().hex(), 16)
    return str(round(abs(num / 2 * 3.14)))[:6]

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = os.path.exists(KEY_FILE)

if not st.session_state['authenticated']:
    st.set_page_config(page_title="Security", layout="centered")
    st.title("Security Activation - Ask the programmer for your password")
    st.warning("Send your Machine ID to programmer email : mulham81ahmed@gmail.com ")

    mid = get_machine_id()
    st.info(f"Machine ID: {mid}")
    pwd = st.text_input("Enter Activation Key:", type="password")
    if st.button("Activate"):
        if pwd == generate_password(mid):
            with open(KEY_FILE, "w") as f: f.write(pwd)
            st.session_state['authenticated'] = True
            st.rerun()
        else:
            st.error("Invalid Activation Key.")
    st.stop()

# ==========================================
# 0. تهيئة مسار ملفات الـ Ephemeris
# ==========================================
EPHE_PATH = "./ephe"
if not os.path.exists(EPHE_PATH):
    os.makedirs(EPHE_PATH)

swe.set_ephe_path(EPHE_PATH)

# ==========================================
# 1. خدمات البيانات الجغرافية والزمنية وحساب إيريس رياضياً
# ==========================================
@st.cache_data
def load_geo_data() -> Tuple[geonamescache.GeonamesCache, Dict[str, str], List[str], Dict[str, List[Dict[str, Any]]]]:
    gc = geonamescache.GeonamesCache()
    countries = gc.get_countries()
    cities = gc.get_cities()

    country_map = {c["name"]: code for code, c in countries.items()}
    sorted_countries = sorted(list(country_map.keys()))

    cities_by_country: Dict[str, List[Dict[str, Any]]] = {}
    for c_code in country_map.values():
        c_cities = [city for city in cities.values() if city["countrycode"] == c_code]
        c_cities_sorted = sorted(c_cities, key=lambda x: x["population"], reverse=True)
        cities_by_country[c_code] = c_cities_sorted

    return gc, country_map, sorted_countries, cities_by_country

gc, country_map, country_list, cities_by_country = load_geo_data()

@st.cache_resource
def get_tz_finder() -> TimezoneFinder:
    return TimezoneFinder()

tf = get_tz_finder()

def get_utc_julian_day(date_obj: datetime.date, time_obj: datetime.time, tz_str: str) -> float:
    local_tz = pytz.timezone(tz_str)
    dt = datetime.datetime.combine(date_obj, time_obj)
    local_dt = local_tz.localize(dt)
    utc_dt = local_dt.astimezone(pytz.utc)
    return swe.julday(
        utc_dt.year,
        utc_dt.month,
        utc_dt.day,
        utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0,
    )

def calculate_eris_longitude(jd: float) -> Tuple[float, float, bool]:
    """
    حساب موقع كويكب إيريس (Eris) رياضياً باستخدام العناصر المدارية الكيبلرية الدقيقة،
    لأنه بديل زحل الحاسم في النظرية الجديدة ولا يكتمل التحليل دونه.
    """
    d = jd - 2451545.0  # الأيام منذ حقبة J2000.0
    period_days = 557.73 * 365.25  # الفترة المدارية لإيريس بالتقريب
    n = 360.0 / period_days  # الحركة الوسطية اليومية بالدرجات
    M0 = 145.5  # الشذوذ الوسطي عند الحقبة
    M = (M0 + n * d) % 360.0
    M_rad = math.radians(M)
    
    # حل معادلة كيبلر للشذوذ اللامركزي E
    e = 0.361  # اللامركزية المدارية لإيريس
    E = M_rad
    for _ in range(10):
        E = M_rad + e * math.sin(E)
        
    v = 2.0 * math.atan(math.sqrt((1 + e) / (1 - e)) * math.tan(E / 2.0))
    r = 67.781 * (1.0 - e * math.cos(E))  
    
    # تحويل الإحداثيات إلى مسار الشمس (Ecliptic Coordinates)
    omega = math.radians(151.6)  # حضيض المدار
    Omega = math.radians(151.0)  # خط العقدة الصاعدة
    inc = math.radians(34.39)    # الميل المداري
    
    u = v + omega
    cos_u = math.cos(u)
    sin_u = math.sin(u)
    cos_Omega = math.cos(Omega)
    sin_Omega = math.sin(Omega)
    cos_i = math.cos(inc)
    
    x = r * (cos_Omega * cos_u - sin_Omega * sin_u * cos_i)
    y = r * (sin_Omega * cos_u + cos_Omega * sin_u * cos_i)
    
    lon = math.degrees(math.atan2(y, x)) % 360.0
    # حساب السرعة الظاهرية التقريبية لتحديد التراجع
    speed = n * (1.0 + e * math.cos(v))
    is_retro = speed < 0 or (d % 365.25 < 180) # تقدير منطقي للحركة التراجعية سنوياً
    
    sign_idx = int(lon // 30)
    deg = lon % 30
    return lon, deg, is_retro

def get_aspect(lon1: float, lon2: float, orb: float = 8.0) -> Optional[Dict[str, Any]]:
    diff = abs(lon1 - lon2)
    if diff > 180:
        diff = 360 - diff

    aspects = {
        "اقتران": {"angle": 0.0, "type": "قوي/محايد", "meaning": "اندماج طاقي مكثف وبداية دورة روحية ونفسية جديدة."},
        "تسديس": {"angle": 60.0, "type": "إيجابي", "meaning": "فرص وعي مواتية تتطلب المبادرة لتفعيلها."},
        "تربيع": {"angle": 90.0, "type": "تحدي/تنشيط", "meaning": "احتكاك داخلي ودفع باتجاه القرارات المصيرية والتحول."},
        "تثليث": {"angle": 120.0, "type": "حماية/تدفق", "meaning": "انسجام تام وتيسير وتدفق سلس للطاقة العليا."},
        "مقابلة": {"angle": 180.0, "type": "مواجهة/استقطاب", "meaning": "حاجة ماسة لإيجاد التوازن الباطني وإعادة تقييم المسار."}
    }

    for name, data in aspects.items():
        if abs(diff - data["angle"]) <= orb:
            return {"name": name, "type": data["type"], "meaning": data["meaning"], "orb": abs(diff - data["angle"])}
    return None

# ==========================================
# 2. الثوابت الفلكية والنظرية النفسية الجديدة
# ==========================================
PLANET_NATURE = {
    "بالاس": "توسع استراتيجي، حكمة إلهية، وقدرة على رؤية الأنماط الكبرى.",
    "إيريس": "حدود كونية، صحوة كرمية حتمية، وعدالة صارمة تهدم القيود البالية.",
    "راهو": "دفع هائل نحو مسارات وتطورات مفصلية جديدة غير مألوفة.",
    "كيتو": "إنهاء دورات كارمية والتحرر الروحي من التعلقات القديمة."
}

ZODIAC_SIGNS = [
    "الحمل", "الثور", "الجوزاء", "السرطان", "الأسد", "العذراء",
    "الميزان", "العقرب", "القوس", "الجدي", "الدلو", "الحوت"
]

SIGN_RULERS = {
    "الحمل": "بلوتو", "الثور": "نبتون", "الجوزاء": "أورانوس", "السرطان": "سيريس",
    "الأسد": "فيستا", "العذراء": "أورانوس", "الميزان": "نبتون", "العقرب": "بلوتو",
    "القوس": "بالاس", "الجدي": "إيريس", "الدلو": "أورانوس", "الحوت": "نبتون"
}

PLANET_DIGNITIES = {
    "فيستا": {"domiciles": ["الأسد"], "exaltation": "الحمل", "detriment": ["الدلو"], "fall": "الميزان"},
    "سيريس": {"domiciles": ["السرطان"], "exaltation": "الثور", "detriment": ["الجدي"], "fall": "العقرب"},
    "أورانوس": {"domiciles": ["الجوزاء", "الدلو"], "exaltation": "العقرب", "detriment": ["الأسد"], "fall": "الثور"},
    "نبتون": {"domiciles": ["الثور", "الميزان", "الحوت"], "exaltation": "السرطان", "detriment": ["العذراء"], "fall": "الجدي"},
    "بلوتو": {"domiciles": ["الحمل", "العقرب"], "exaltation": "الأسد", "detriment": ["الثور"], "fall": "الدلو"},
    "بالاس": {"domiciles": ["القوس", "الجوزاء"], "exaltation": "السرطان", "detriment": ["الجدي", "الحوت"], "fall": "الجدي"},
    "إيريس": {"domiciles": ["الجدي"], "exaltation": "الميزان", "detriment": ["السرطان", "الأسد"], "fall": "الحمل"}
}

HOUSE_TEMPORAL_CATEGORY = {
    1: {"realm": "الحاضر", "desc": "الذات، الهوية العليا، المظهر، والمبادرات الروحية."},
    2: {"realm": "المستقبل", "desc": "القيمة الذاتية، الموارد الباطنية، والاستثمار الروحي."},
    3: {"realm": "الماضي", "desc": "المحيط القريب، التواصل، الفكر الواعي، والخبرات المبكرة."},
    4: {"realm": "الحاضر", "desc": "الجذور، العقل الباطن، الاستقرار العاطفي الداخلي."},
    5: {"realm": "المستقبل", "desc": "الإبداع النقي، الشغف، والتعبير عن الهوية الأسمى."},
    6: {"realm": "الماضي", "desc": "الروتين اليومي، التهذيب النفسي، والتطهير الداخلي."},
    7: {"realm": "الحاضر", "desc": "الشراكات المقدسة، المرآة النفسية، والتوازن التفاعلي."},
    8: {"realm": "المستقبل", "desc": "التحولات الجذرية، البعث من الرماد، والعمق الباطني."},
    9: {"realm": "الماضي", "desc": "الحكمة العليا، الفلسفة الكونية، والمعتقدات المكتسبة."},
    10: {"realm": "الحاضر", "desc": "الرسالة القدرية الكبرى، المكانة الروحية، والإنجاز."},
    11: {"realm": "المستقبل", "desc": "الوعي الجمعي، الشبكات الكونية، والأهداف العليا."},
    12: {"realm": "الماضي", "desc": "البيئة الباطنية العميقة، العزلة المقدسة، والكارما."}
}

BODIES = {
    "فيستا": swe.VESTS if hasattr(swe, 'VESTS') else swe.VESTA,  # بديلة الشمس
    "سيريس": swe.CERES,       # بديلة القمر
    "أورانوس": swe.URANUS,    # بديل عطارد
    "نبتون": swe.NEPTUNE,    # بديل الزهرة
    "بلوتو": swe.PLUTO,      # بديل المريخ
    "بالاس": swe.PALLAS,     # بديل المشتري
    "راهو": swe.TRUE_NODE,
}

ASTEROIDS = {
    "كايرون": swe.CHIRON,
    "جونو": swe.JUNO,
    "هايجيا": 10010,
    "ليليث": swe.MEAN_APOG,
}

RULER_IN_HOUSE_MEANINGS = {
    1: {
        1: "استقلال تام في بناء الهوية الروحية والاعتماد الكلي على الوعي الذاتي السامي.",
        2: "توجيه الطاقة الشخصية نحو تفعيل الموارد الباطنية واكتشاف القيمة الكبرى للذات.",
        3: "تركيز النشاط الشخصي على الإلهام الفكري، التواصل الواعي، والتأثير بالمحيط.",
        4: "ارتباط وثيق بالجذور الباطنية، العقل الباطن، وبناء الاستقرار النفسي الداخلي.",
        5: "توجيه الذات نحو الشغف الإبداعي النقي، التعبير الروحي، والمغامرة العليا.",
        6: "الانغماس في الروتين الواعي، التهذيب النفسي المستمر، والانضباط الباطني.",
        7: "تحديد الهوية والمسار عبر الشراكات المقدسة والتفاعل العميق مع الآخر.",
        8: "اهتمام بالغ بالتحولات الجذرية، الولادة الجديدة، والعلوم الباطنية العميقة.",
        9: "طموح روحي نحو استكشاف الحكمة الكونية، الفلسفة العليا، والأسفار الباطنية.",
        10: "السعي الفائق نحو إنجاز الرسالة القدرية الكبرى وتحقيق المكانة الروحية.",
        11: "توجيه الطاقة نحو الاتصال بشبكة الوعي الجمعي وتحقيق الأهداف الكونية.",
        12: "ميل للعزلة المقدسة، التأمل العميق، والتواصل مع العوالم الخفية والباطنية."
    },
    2: {
        1: "القيمة والثروة الروحية تأتي بجهد ذاتي خالص واعتماد على المهارات الباطنية.",
        2: "مصادر استقرار نفسي ومادي ثابتة، وقدرة استثنائية على إدارة الطاقة الذاتية.",
        3: "تأتي الموارد من التعبير الفكري الراقي، النشر، الكلمة المضيئة، والاتصال الواعي.",
        4: "تأتي الثروة الباطنية من العمق العائلي، التراث الروحي، والاستقرار الداخلي.",
        5: "تأتي القيمة والموارد من الإبداع النقي، المشاريع الملهمة، والتعبير عن البهجة.",
        6: "تأتي الموارد من الانضباط اليومي، الخدمة الواعية، والتهذيب الذاتي المستمر.",
        7: "تأتي الثروة الروحية والمادية من الشراكات المقدسة والعقود الواعية مع الآخرين.",
        8: "تأتي الموارد من التحولات الكبرى، التركات الروحية، وإدارة الطاقات المشتركة.",
        9: "تأتي الثروة من الحكمة العليا، الأسفار البعيدة، والتجربة الفلسفية الواسعة.",
        10: "تأتي الموارد من الإنجازات المهنية الكبرى والسمعة الروحية المرموقة.",
        11: "تأتي الثروة من شبكة العلاقات الكونية والمشاريع الجماعية الملهمة.",
        12: "تأتي الموارد من العمل الخفي خلف الكواليس والمؤسسات الروحية والباطنية."
    },
    3: {
        1: "تأثير الفكر الكوني والمهارات الحدسية مباشرة على تكوين الشخصية والهوية.",
        2: "استغلال الإلهام الفكري والمعرفي في تحقيق الاستقرار النفسي والمادي.",
        3: "ذكاء استراتيجي متقد في التواصل، وعلاقات عميقة مع المحيط القريب والأخوة.",
        4: "التواصل والنشاط الذهني يتركز حول استكشاف العقل الباطن وأسرار النفس.",
        5: "توظيف الفكر الملهم في الفنون، الإبداع النقي، والرسائل التعبيرية السامية.",
        6: "استخدام الذهن الواعي في تنقية الروتين اليومي وتحقيق التوازن النفسي والجسدي.",
        7: "تواصل واعٍ يساهم في إنجاح الشراكات الحياتية والحوارات الروحية العميقة.",
        8: "اهتمام بالأبحاث النفسية العميقة، السيمياء، وفك أسرار الطاقات الخفية.",
        9: "دمج المعرفة الحدسية بالعلوم الكونية العليا والدراسات الفلسفية المتقدمة.",
        10: "استغلال مهارات التواصل الكوني للوصول إلى مناصب إرشادية وتنويرية.",
        11: "توظيف الأفكار المبتكرة في خدمة الجماعات وشبكات الوعي الجمعي.",
        12: "التفكير الصامت، التأمل الباطني، والاتصال بالمعارف السرية."
    },
    4: {
        1: "تأثير قوي للجذور الباطنية والوعي الجمعي العائلي على بناء الشخصية العليا.",
        2: "الاستقرار الداخلي والأمان النفسي يعززان الموارد الروحية والقوة الباطنية.",
        3: "التواصل الأسري يتسم بالعمق الفكري والتبادل الرؤيوي المستمر.",
        4: "تعلق شديد بالوطن الداخلي، والسكينة الباطنية، والاستقرار الروحي العميق.",
        5: "البيت هو مسرح الإلهام الروحي والبهجة العائلية والأجواء النبيلة.",
        6: "المسؤوليات الداخلية ترتبط بالتهذيب الذاتي والعناية بصحة النفس والجسد.",
        7: "دعم عاطفي وروحاني عميق للشراكات وتأسيس بيت قائم على الوعي.",
        8: "تحولات جذرية في البيئة الباطنية والعائلية نحو التحرر والنمو الروحي.",
        9: "تأسيس الاستقرار في أبعاد فكرية واسعة أو الانحدار من جذور متعددة الأبعاد.",
        10: "الاسم الروحي والجذور تسهم بشكل مباشر في رفع المكانة والرسالة.",
        11: "المنزل ملتقى للأرواح المتشابهة، وتحقيق أهداف إنسانية مشتركة.",
        12: "خصوصية عالية في الشؤون الداخلية، وميل دائم للعزلة والتأمل الهادئ."
    },
    5: {
        1: "شخصية ملهمة، محبة للجمال والإبداع، وتجذب الأضواء بروحها السامية.",
        2: "الاستثمار في المجالات الإبداعية والنقية يجلب وفورات روحية ومادية.",
        3: "التعبير الإبداعي عبر الكتابة الواعية، الفنون الكونية، والإلهام السريع.",
        4: "محبة الأجواء العائلية الراقية، وتوجيه الطاقة الإبداعية نحو تجميل السكن.",
        5: "حظوظ مضاعفة في الفنون الروحية، الإبداع المطلق، والاتصال بالبهجة العليا.",
        6: "تحويل الشغف الإبداعي إلى خدمة يومية واعية وعطاء ملموس.",
        7: "علاقات عاطفية سامية تؤدي إلى شراكات قائمة على الحب الإلهي والتفاهم.",
        8: "استثمارات روحية عميقة ومشاريع قائمة على التحول والتجدد الخلوي والنفسي.",
        9: "السعادة والبهجة في الأسفار الكونية، استكشاف الثقافات، والحكمة الفلسفية.",
        10: "الوصول للمكانة والنجاح عبر الأعمال الإبداعية والمواهب الروحية الفريدة.",
        11: "تحقيق أمنيات كبرى عبر المشاريع الفنية والجماعية الملهمة.",
        12: "إبداع خفي وأعمال فنية تصنع في سرية تامة بعيداً عن صخب العالم."
    },
    6: {
        1: "انعكاس مباشر للروتين الواعي والتهذيب النفسي على الحيوية والصفاء.",
        2: "الجهد والعمل اليومي المنضبط هو المصدر الرئيسي لتأمين الاستقرار.",
        3: "العمل اليومي يتطلب الإلهام الذهني، التنقل الواعي، والمهام التنويرية.",
        4: "العمل من العمق الداخلي، أو الانشغال بترتيب الطاقات والبيئة النفسية.",
        5: "تنظيم الروتين العملي لخدمة المشاريع الإبداعية أو رعاية الأرواح الشابة.",
        6: "تركيز عالٍ جداً على الانضباط الواعي، الجودة الروحية، والشفاء الذاتي.",
        7: "العمل اليومي يرتبط بخدمة الشريك أو مساندة الآخرين برحمة ومحبة.",
        8: "العمل في مجالات التطوير النفسي العميق، الشفاء، وإدارة التحولات.",
        9: "العمل في مجالات الحكمة العليا، الاستشارات الكونية، أو الإرشاد الروحي.",
        10: "الالتزام والعمل الواعي يقودان للترقي والوصول لمناصب قيادية إنسانية.",
        11: "العمل ضمن مجموعات واعية تدعم أهداف الخدمة الكونية والإنسانية.",
        12: "العمل في مجالات التأمل، العزلة، أو تقديم الدعم النفسي الخفي."
    },
    7: {
        1: "الشريك (الروحي أو التجاري) يمثل مرآة حقيقية توجه مسارك وتطور وعيك.",
        2: "تتأثر مواردك واستقرارك بشكل مباشر بالشراكات والعلاقات المتبادلة.",
        3: "الشريك يشاركك التفكير الكوني، الفهم العميق، والتبادل الفكري الراقي.",
        4: "دعم الشريك لبناء استقرار روحي وعائلي وملاذ آمن للروح.",
        5: "شراكة قائمة على الحب الإلهي، الانسجام السامي، والتعبير الخلاق.",
        6: "الشريك يشاركك الروتين الواعي ومسيرة التهذيب والعمل اليومي.",
        7: "شراكات مقدسة متوازنة ورغبة عميقة في بناء روابط واعية ومستقرة.",
        8: "شراكة روحية عميقة، تحولات مشتركة، وتطهير متبادل للأعماق.",
        9: "الشريك يحمل أبعاداً ثقافية أو روحية واسعة أو يتم التعرف عليه برحلة.",
        10: "الشريك يدعم رسالتك القدرية ومكانتك الاجتماعية والروحية.",
        11: "الشريك يأتي من دائرة الوعي المشترك والشبكات الإنسانية الداعمة.",
        12: "علاقة تتسم بالخصوصية الروحية العالية والاتصال الباطني الهادئ."
    },
    8: {
        1: "قدرة خارقة على التجدد والبعث النفسي السريع بعد الأزمات والتحولات.",
        2: "تغيرات عميقة في الثروة والموارد تأتي من التحولات الكبرى أو الإرث الروحي.",
        3: "سرية وتكتم في الغوص الفكري، وميل دائم للتحليل الباطني العميق.",
        4: "تحولات جذرية في البيئة الداخلية أو اكتشاف كنوز باطنية عائلية.",
        5: "استثمارات جريئة ومشاريع قائمة على إعادة التدوير النفسي والروحي.",
        6: "العمل في مجالات التطوير الذاتي، إدارة الأزمات، أو الشفاء الباطني.",
        7: "إدارة الطاقات المشتركة مع الشريك والالتزام بعقود تحويلية عميقة.",
        8: "قوة باطنية جبارة، اهتمام بالعلوم الخفية، وقدرة فريدة على الشفاء والتحول.",
        9: "أبحاث فلسفية وكونية عميقة، ودراسة العلوم الباطنية المتقدمة.",
        10: "السلطة والترقي يأتيان من خلال إدارة التحولات الكبرى وإصلاح المؤسسات.",
        11: "الدعم المالي والروحي يأتي عبر الشبكات الكونية والمشاريع التحويلية.",
        12: "اهتمام بالغ بالعلوم الروحية، العلاج الباطني، والتحرر من كارما الماضي."
    },
    9: {
        1: "شخصية متطلعة، شغوفة بالحكمة الكونية، الفلسفة، والتوسع الروحي.",
        2: "الأرباح والموارد تأتي من النشاط الإرشادي، النشر الكوني، أو الأسفار.",
        3: "دمج المعرفة العليا بالتطبيقات العملية والتواصل الواعي مع المحيط.",
        4: "الهجرة الروحية، الإقامة الواعية، أو تأثير الفلسفة على الاستقرار الداخلي.",
        5: "المتعة والشغف يكمنان في السفر الكوني، استكشاف الحكمة، ونشر الإلهام.",
        6: "العمل في مجالات التعليم الراقي، الإرشاد، النشر، أو الاستشارات الكونية.",
        7: "الشراكات ترتبط بأرواح من خلفيات فلسفية أو ثقافية أجنبية ومتنوعة.",
        8: "أبحاث كونية وفلسفية عميقة، ودراسة العلوم الباطنية والمتافيزيقيا.",
        9: "تألق استثنائي في الحكمة العليا، الأسفار الكونية، والاتصال بالنور.",
        10: "الوصول إلى السمعة الطيبة والمناصب المرموقة عبر العلم والإرشاد.",
        11: "توسيع شبكة الأرواح على مستوى كوني، وتحقيق أهداف فكرية وإنسانية.",
        12: "السفر بهدف الاستجمام الروحي، التأمل الباطني، والاتصال بالأسرار الكونية."
    },
    10: {
        1: "شخصية قيادية ملهمة، حضور طاقي قوي، والنجاح مرهون بالرسالة الواعية.",
        2: "النجاح والموقع المرموق يحققان استقراراً مادياً وروحياً ممتازاً.",
        3: "المهنة تعتمد على وسائل الإلهام، النشر الكوني، والتواصل الواسع.",
        4: "إدارة المشاريع ذات الجذور العميقة، أو العمل في مجالات الباطن والعقارات.",
        5: "المهنة في المجالات الفنية الملهمة، الإبداع، أو توجيه الأجيال الجديدة.",
        6: "الوصول للمناصب القيادية من خلال الانضباط الواعي والخدمة الإنسانية.",
        7: "النجاح المهني قائم على عقد الشراكات الواعية والدبلوماسية الروحية.",
        8: "إدارة المؤسسات التحويلية، الاستثمارات الكبرى، أو العلوم الباطنية.",
        9: "المهنة في مجالات السفر الكوني، الدبلوماسية الروحية، والتعليم العالي.",
        10: "طموح روحي استثنائي، مكانة بارزة، وتحقيق الرسالة القدرية الكبرى.",
        11: "قيادة شبكات الوعي الجمعي، وبناء التحالفات الكونية الواسعة.",
        12: "المهنة خلف الكواليس، إدارة المؤسسات الروحية، أو التخطيط الاستراتيجي الخفي."
    },
    11: {
        1: "شخصية محبوبة كونياً، ولديها القدرة على جذب الأرواح الداعمة والشبكات.",
        2: "العلاقات الاجتماعية والكونية تفتح آفاقاً جديدة للمكاسب والفرص المضيئة.",
        3: "علاقات ممتازة مع المجموعات الفكرية والتواصل الكوني السلس والواعي.",
        4: "دعم الأرواح الصديقة لتثبيت الاستقرار النفسي والعقاري الداخلي.",
        5: "الأصدقاء يشاركونك الشغف بالفنون الكونية، الإبداع، والمشاريع الملهمة.",
        6: "تحقيق الأهداف من خلال التعاون الواعي في خدمة المجموعات الإنسانية.",
        7: "تحول علاقة الوعي إلى شراكة روحية أو عمل مستقر ومثمر.",
        8: "تلقي دعم روحي أو مادي كبير من الشبكات والمنظمات الكونية لتحقيق رسالتك.",
        9: "أصدقاء وعلاقات كونية من أبعاد مختلفة تدعم طموحاتك الفلسفية.",
        10: "شبكة علاقات وازنة تساعدك في الوصول للترقية والسمعة الروحية العالية.",
        11: "تحقيق أهداف وطموحات كبرى، وحضور بارز ضمن الجمعيات الكونية.",
        12: "أصدقاء مخلصون يعملون على دعمك في الخفاء، واهتمام بالأنشطة الإنسانية."
    },
    12: {
        1: "شخصية عميقة هادئة، ميل للتأمل والتمتع بالخصوصية والأسرار الكونية.",
        2: "الإنفاق أو المكاسب ترتبط بمؤسسات خفية، أبعاد سرية، أو أبعاد كونية بعيدة.",
        3: "التفكير العميق والبحث عن السكينة النفسية لتصفية الذهن والتأمل المطلق.",
        4: "الرغبة في العيش في ملاذ هادئ ومعزول لتوفير السلام الروحي والراحة.",
        5: "ممارسة المواهب الإبداعية في خفاء وسرية تامة بعيداً عن صخب الأضواء.",
        6: "تقديم خدمات رعاية وتضحية واعية، والاهتمام بالصحة الباطنية والشفاء.",
        7: "شراكات أو علاقات تحتاج للعناية والتكتم لتجنب المشتتات الخارجية.",
        8: "دراسات روحية ونفسية عميقة وقدرة عالية على التحرر من ترومات الماضي.",
        9: "السفر الباطني بهدف الاستجمام الروحي والاتصال بالأسرار الكونية.",
        10: "العمل المهني الاستراتيجي بعيداً عن الأنظار، أو إدارة الأنشطة غير المعلنة.",
        11: "مساعدة الآخرين والقيام بالأنشطة الإنسانية والخيرية في الخفاء التام.",
        12: "عالم داخلي غني جداً، طاقات روحانية عالية، وحماية باطنية مطلقة."
    }
}

# ==========================================
# 3. محرك التحليل النفسي والروحي العميق (DeepPsychologicalAnalyzer)
# ==========================================
class DeepPsychologicalAnalyzer:
    def __init__(self):
        self.spiritual_bodies = {
            "فيستا": {
                "role": "بديلة الشمس (الجوهر والأنا العليا)",
                "meaning": "شعلة الوعي النقي، النار المقدسة الداخلية، والتركيز المطلق على الهوية الأسمى والهدف الجوهري بعيداً عن الغرور السطحي.",
                "psych": "التفاني الفائق، الانضباط الروحي العالي، والاتصال بالجوهر النوراني."
            },
            "سيريس": {
                "role": "بديلة القمر (العالم العاطفي والنفسي)",
                "meaning": "الأمومة الكونية، الرعاية العاطفية الخالصة، الاحتضان، والتغذية الروحية والتعامل مع دورات الحياة والفقد والنمو الداخلي.",
                "psych": "الأمان العاطفي، الاحتضان الداخلي، استعادة التوازن النفسي، ودورات النمو الباطني."
            },
            "أورانوس": {
                "role": "بديل عطارد (الفكر والتواصل)",
                "meaning": "العقل الكوني الأعلى، الإلهام المفاجئ، العبقرية، والاتصال بشبكة الوعي الجمعي متجاوزاً حدود التفكير اليومي.",
                "psych": "الإشراقات الذهنية الخاطفة، التحرر الفكري، الرؤى المستقبلية، والعبقرية التحليلية."
            },
            "نبتون": {
                "role": "بديل الزهرة (الحب والعلاقات)",
                "meaning": "المحبة الإلهية المطلقة، التسامي الفني والروحي، الذوبان في الجمال الكوني الخالص، والرحمة الشاملة.",
                "psych": "الحساسية الفنية المرتفعة، الخيال الخصب، الشفقة الكونية، والتسامي العاطفي."
            },
            "بلوتو": {
                "role": "بديل المريخ (الطاقة والإرادة)",
                "meaning": "الإرادة الإلهية الكبرى، طاقة التحول الجذري، التطهير النفسي العميق، والقدرة على البعث والسيطرة المطلقة من الرماد.",
                "psych": "القوة الباطنية الجبارة، التحول الجذري، تجاوز الصدمات (Trauma)، والسيادة النفسية."
            },
            "بالاس": {
                "role": "بديل المشتري (الحكمة والتوسع)",
                "meaning": "العقل الاستراتيجي فائق الذكاء، التخطيط المنظم، الحكمة الإلهية، والقدرة على رؤية الأنماط الكبرى وإيجاد الحلول الشاملة.",
                "psych": "الذكاء الاستراتيجي، الربط بين المفاهيم المعقدة، التخطيط بعيد المدى، والحكمة الواسعة."
            },
            "إيريس": {
                "role": "بديل زحل (الحدود والكارما والعدالة)",
                "meaning": "الحد الكوني الأقصى، الصحوة الكرمية الحتمية، الحقيقة المطلقة التي لا تقبل التزييف، والعدالة الصارمة التي تهدم القيود البالية.",
                "psych": "كسر الأطر التقليدية، قول الحقيقة الصريحة، التحرر من القيود الموروثة، والعدالة الذاتية."
            },
            "راهو": {
                "role": "عقدة التطور والمصير (المسار الصاعد)",
                "meaning": "الشغف الكوني المستقبلي، الوجهة القدرية التي تدفع الروح للنمو والتطور عبر تجارب جديدة.",
                "psych": "التطلع نحو المستقبل، التغلب على المخاوف، واكتشاف آفاق جديدة للوعي."
            },
            "كيتو": {
                "role": "الجذور الكرمية والتحرر (المسار الهابط)",
                "meaning": "الخبرات المتراكمة من الماضي، التحرر من التعلقات القديمة، والتخلي عن الأنماط الاستهلاكية.",
                "psych": "الحكمة الموروثة، التخلص من الأثقال النفسية، والوصول للسلام الداخلي."
            }
        }

        self.asteroids_psych = {
            "كايرون": "الجرح المقدس؛ يشير إلى نقطة التحول والتشافي الباطني حيث تتحول آلامك إلى حكمة وقدرة على إرشاد الآخرين.",
            "جونو": "الشراكة المقدسة والتوازن الروحي؛ يحكم التناغم في العلاقات العميقة والالتزام المتبادل القائم على الوعي.",
            "هايجيا": "الطب الوقائي الروحي والتطهير؛ يحكم النظافة الطاقية، الروتين الواعي، ومنع تلوث الوعي.",
            "ليليث": "الظل النفسي المكبوت؛ يمثل القوة الدفينة، التحرر من القيود الاجتماعية، ومواجهة الأعماق الخفية للذات."
        }

    def analyze_placement(self, body: str, sign: str, house: int, is_asteroid: bool = False) -> str:
        house_name = f"البيت {house}"
        if is_asteroid:
            body_info = self.asteroids_psych.get(body, "دلالة نفسية وعميقة متقدمة")
            return (
                f"<b>التحليل النفسي للكويكب ({body}) في برج ({sign}) - ({house_name}):</b><br>"
                f"• <b>الدلالة الباطنية:</b> {body_info}<br>"
                f"• <b>سياق البيت ({house_name}):</b> {HOUSE_TEMPORAL_CATEGORY.get(house, {}).get('desc', '')}<br>"
            )

        p_info = self.spiritual_bodies.get(body, {})
        return (
            f"<b>التحليل النجمي والنفسي لـ ({body}) [{p_info.get('role', '')}] في برج ({sign}) - ({house_name}):</b><br>"
            f"• <b>الجوهر والدلالة:</b> {p_info.get('meaning', '')}<br>"
            f"• <b>المحفز النفسي:</b> {p_info.get('psych', '')}<br>"
            f"• <b>سياق البيت ({house_name}):</b> {HOUSE_TEMPORAL_CATEGORY.get(house, {}).get('desc', '')}<br>"
        )

    def analyze_aspect(self, body1: str, body2: str, aspect_name: str, house1: int = 0, house2: int = 0) -> str:
        return (
            f"<b>التفاعل الروحي والنفسي ({aspect_name}) بين ({body1}) و ({body2}):</b><br>"
            f"• <b>طبيعة الاتصال:</b> تداخل طاقي مكثف بين قطبين من السباعية الروحية في ({f'البيت {house1}'}) و ({f'البيت {house2}'}).<br>"
            f"• <b>الدلالة الباطنية:</b> يعيد هذا التفاعل صياغة مسارك الروحي، مولداً طاقة دفع كبرى نحو الوعي والتحول أو إعادة التوازن الداخلي.<br>"
        )

    def generate_psychological_summary(self, placements: List[Dict[str, Any]], stelliums: Dict[str, int]) -> Tuple[List[str], List[str], List[str], List[str]]:
        core_status = []
        psych_status = []
        spiritual_advice = []
        integration_plan = []

        if stelliums:
            for st_sign, count in stelliums.items():
                core_status.append(
                    f"✨ <b>تركيز طاقي مكثف (Stellium) في برج {st_sign}:</b> وجود {count} أجرام يفرز طاقة مكثفة للغاية توجه تركيزك وقدراتك الكبرى نحو سمات هذا البرج."
                )

        for p in placements:
            b_name = p["body"]
            if b_name == "فيستا":
                spiritual_advice.append("🔥 <b>شعلة فيستا (جوهرك الأسمى):</b> كرس طاقاتك القيادية ونارك المقدسة في رسالتك الكبرى وترك بصمة واضحة.")
            elif b_name == "سيريس":
                spiritual_advice.append("🌿 <b>رعاية سيريس (عالمك العاطفي):</b> استعد أمانك النفسي عبر الاحتواء، الكلمة الطيبة، والتغذية الروحية للمحيط.")
            elif b_name == "بالاس":
                spiritual_advice.append("🦉 <b>حكمة بالاس (عقلك الاستراتيجي):</b> استثمر ذكاءك التحليلي الفائق في صياغة الرؤى طويلة الأجل وبناء الأنماط الكبرى.")
            elif b_name == "إيريس":
                spiritual_advice.append("⚖️ <b>عدالة إيريس (حدودك وكارماك):</b> ارفض القيود البالية، واصدع بالحقيقة المطلقة لتحقيق العدالة والسيادة الذاتية.")

        integration_plan.append("✔️ **التأمل الواعي:** تخصيص وقت يومي لتصفية الذهن والاتصال بالوعي الكوني الأعلى.")
        integration_plan.append("✔️ **تدوين الرؤى:** تسجيل الإشراقات الفكرية والأحلام لاستنطاق العقل الباطن.")
        integration_plan.append("✔️ **التوازن النفسي:** ممارسة التحرر العاطفي وتقبل دورات التحول والنمو الداخلي برحابة صدر.")

        if not core_status:
            core_status.append("🟢 الخارطة تظهر توزيعاً متوازناً لطاقات السباعية الروحية.")
        if not spiritual_advice:
            spiritual_advice.append("✔️ انسجام عام بين الأجرام العليا والمسار القدري.")

        return core_status, psych_status, spiritual_advice, integration_plan

# ==========================================
# 4. محرك التحليل الفلكي الشامل (AstroEngine)
# ==========================================
class AstroEngine:
    def __init__(self, jd: float, lat: float, lng: float):
        self.jd = jd
        self.lat = lat
        self.lng = lng
        self.planets_data = []
        self.aspects_data = []
        self.ascendant_sign_idx = 0
        self.ascendant_deg = 0.0
        self.mc_deg = 0.0
        self._calculate_chart()

    def _calculate_chart(self):
        # حساب البيوت بنظام كل برج بيت (Whole Sign Houses - b'W')
        cusps, ascmc = swe.houses(self.jd, self.lat, self.lng, b'W')
        self.ascendant_deg = ascmc[0]
        self.mc_deg = ascmc[1]
        self.ascendant_sign_idx = int(self.ascendant_deg // 30)

        flags = swe.FLG_SWIEPH | swe.FLG_SPEED

        # حساب الأجرام الأساسية (السباعية الروحية + راهو)
        for b_name, b_id in BODIES.items():
            try:
                pos, _ = swe.calc_ut(self.jd, b_id, flags)
                lon = pos[0]
                speed = pos[3]
            except Exception:
                lon, speed = 0.0, 1.0
            
            sign_idx = int(lon // 30)
            deg = lon % 30
            is_retro = speed < 0

            house_num = ((sign_idx - self.ascendant_sign_idx) % 12) + 1

            self.planets_data.append({
                "body": b_name,
                "lon": lon,
                "sign": ZODIAC_SIGNS[sign_idx],
                "sign_idx": sign_idx,
                "degree": deg,
                "house": house_num,
                "is_retro": is_retro,
                "is_asteroid": False
            })

        # حساب كيتو كمعاكس لراهو (180 درجة)
        rahu_item = next((p for p in self.planets_data if p["body"] == "راهو"), None)
        if rahu_item:
            ketu_lon = (rahu_item["lon"] + 180) % 360
            ketu_sign_idx = int(ketu_lon // 30)
            ketu_house = ((ketu_sign_idx - self.ascendant_sign_idx) % 12) + 1
            self.planets_data.append({
                "body": "كيتو",
                "lon": ketu_lon,
                "sign": ZODIAC_SIGNS[ketu_sign_idx],
                "sign_idx": ketu_sign_idx,
                "degree": ketu_lon % 30,
                "house": ketu_house,
                "is_retro": True,
                "is_asteroid": False
            })

        # حساب إيريس (Eris) بديلة زحل رياضياً بدقة متناهية
        eris_lon, eris_deg, eris_retro = calculate_eris_longitude(self.jd)
        eris_sign_idx = int(eris_lon // 30)
        eris_house = ((eris_sign_idx - self.ascendant_sign_idx) % 12) + 1
        self.planets_data.append({
            "body": "إيريس",
            "lon": eris_lon,
            "sign": ZODIAC_SIGNS[eris_sign_idx],
            "sign_idx": eris_sign_idx,
            "degree": eris_deg,
            "house": eris_house,
            "is_retro": eris_retro,
            "is_asteroid": False
        })

        # حساب الكويكبات النفسية والـ نقاط الأخرى
        for a_name, a_id in ASTEROIDS.items():
            try:
                pos, _ = swe.calc_ut(self.jd, a_id, flags)
                lon = pos[0]
                sign_idx = int(lon // 30)
                deg = lon % 30
                house_num = ((sign_idx - self.ascendant_sign_idx) % 12) + 1
                self.planets_data.append({
                    "body": a_name,
                    "lon": lon,
                    "sign": ZODIAC_SIGNS[sign_idx],
                    "sign_idx": sign_idx,
                    "degree": deg,
                    "house": house_num,
                    "is_retro": pos[3] < 0,
                    "is_asteroid": True
                })
            except Exception:
                pass

        # حساب الاتصالات بين جميع الأجرام
        for b1, b2 in itertools.combinations(self.planets_data, 2):
            asp = get_aspect(b1["lon"], b2["lon"], orb=7.5)
            if asp:
                self.aspects_data.append({
                    "body1": b1["body"],
                    "house1": b1["house"],
                    "body2": b2["body"],
                    "house2": b2["house"],
                    "aspect": asp["name"],
                    "type": asp["type"],
                    "meaning": asp["meaning"],
                    "orb": asp["orb"]
                })

    def evaluate_ruler_strength(self, ruler_name: str, sign_name: str, house_num: int, is_retro: bool) -> Dict[str, Any]:
        score = 0
        reasons = []

        dig = PLANET_DIGNITIES.get(ruler_name, {})
        if sign_name in dig.get("domiciles", []):
            score += 5
            reasons.append("في موطنه الأصلي - قوة ممتازة")
        elif sign_name == dig.get("exaltation"):
            score += 4
            reasons.append("في شرفه - طاقة عالية وتألق")
        elif sign_name in dig.get("detriment", []):
            score -= 4
            reasons.append("في وباله - صعوبة في التعبير عن طاقته")
        elif sign_name == dig.get("fall"):
            score -= 5
            reasons.append("في هبوطه - إحباط وطاقة مستنزفة")
        else:
            reasons.append("في موقع محايد")

        if house_num in [1, 4, 7, 10]:
            score += 3
            reasons.append("في بيت وتدي (الحاضر) - تأثير قوي وواضح")
        elif house_num in [2, 5, 8, 11]:
            score += 1
            reasons.append("في بيت معقب (المستقبل) - بناء وثبات تدريجي")
        else:
            score -= 2
            reasons.append("في بيت زائل (الماضي) - طاقة خفية أو بطيئة الظهور")

        if is_retro:
            score -= 2
            reasons.append("الحاكم متراجع - مراجعة داخلية وتأقلم عميق")

        status = "قوي جداً" if score >= 5 else ("متوسط القوة" if score >= 1 else "ضعيف / مجهد")
        return {"score": score, "status": status, "reasons": reasons}

    def analyze_house_rulers(self) -> List[Dict[str, Any]]:
        rulers_report = []
        for h_num in range(1, 13):
            h_sign_idx = (self.ascendant_sign_idx + h_num - 1) % 12
            h_sign = ZODIAC_SIGNS[h_sign_idx]
            ruler_name = SIGN_RULERS.get(h_sign, "فيستا")

            ruler_p = next((p for p in self.planets_data if p["body"] == ruler_name), None)

            if ruler_p:
                eval_res = self.evaluate_ruler_strength(ruler_name, ruler_p["sign"], ruler_p["house"], ruler_p["is_retro"])
                temp_cat = HOUSE_TEMPORAL_CATEGORY[h_num]

                ruler_meaning = RULER_IN_HOUSE_MEANINGS.get(h_num, {}).get(
                    ruler_p["house"], "تأثير متداخل بين طاقات البيتين والمسار الروحي."
                )

                rulers_report.append({
                    "house_num": h_num,
                    "house_sign": h_sign,
                    "ruler": ruler_name,
                    "ruler_sign": ruler_p["sign"],
                    "ruler_house": ruler_p["house"],
                    "ruler_meaning": ruler_meaning,
                    "is_retro": ruler_p["is_retro"],
                    "status": eval_res["status"],
                    "score": eval_res["score"],
                    "reasons": eval_res["reasons"],
                    "realm": temp_cat["realm"],
                    "realm_desc": temp_cat["desc"]
                })
        return rulers_report

    def get_julian_day(self, year: int, month: int, day: int) -> float:
        return swe.julday(year, month, day, 12.0)

    def get_ecliptic_longitude(self, jd: float, body_id: int) -> float:
        flags = swe.FLG_SWIEPH | swe.FLG_SPEED
        pos, _ = swe.calc_ut(jd, body_id, flags)
        return pos[0]

    def get_sign_from_longitude(self, lon: float):
        sign_idx = int(lon // 30)
        return sign_idx, ZODIAC_SIGNS[sign_idx]

    def calculate_whole_sign_house(self, asc_sign_idx: int, planet_sign_idx: int) -> int:
        return ((planet_sign_idx - asc_sign_idx) % 12) + 1

    def generate_3year_forecast(self) -> List[Dict[str, Any]]:
        current_year = datetime.datetime.now().year
        forecasts = []
        target_sign_idx = self.ascendant_sign_idx

        domain_houses = {
            "spiritual_growth": [1, 9, 12],
            "relationships_soul": [7],
            "transformation": [8],
            "career_mission": [10],
            "inner_stability": [2, 4]
        }

        rulers_of_houses = {}
        natal_ruler_lons = {}
        
        for h in [1, 2, 4, 7, 8, 9, 10, 12]:
            s_idx = (target_sign_idx + h - 1) % 12
            s_name = ZODIAC_SIGNS[s_idx]
            ruler = SIGN_RULERS.get(s_name, "فيستا")
            rulers_of_houses[h] = ruler
            
            r_data = next((p for p in self.planets_data if p["body"] == ruler), None)
            if r_data:
                natal_ruler_lons[h] = r_data["lon"]

        outer_planets = {
            "بالاس": swe.PALLAS,
            "أورانوس": swe.URANUS,
            "نبتون": swe.NEPTUNE,
            "بلوتو": swe.PLUTO,
            "راهو": swe.TRUE_NODE,
        }

        for i in range(3):
            yr = current_year + i
            jd_mid = self.get_julian_day(yr, 7, 1)

            transits = {}
            for p_name, p_id in outer_planets.items():
                lon = self.get_ecliptic_longitude(jd_mid, p_id)
                s_idx, s_name = self.get_sign_from_longitude(lon)
                house = self.calculate_whole_sign_house(target_sign_idx, s_idx)
                transits[p_name] = {"lon": lon, "house": house, "sign": s_name}
                
            year_data = {"year": yr}
            
            for domain_key, h_list in domain_houses.items():
                insights = []
                for h in h_list:
                    r_name = rulers_of_houses.get(h)
                    r_lon = natal_ruler_lons.get(h)
                    
                    for t_planet, t_data in transits.items():
                        impact_text = PLANET_NATURE.get(t_planet, "دعم وتوسع طاقي روحي.")
                        if t_data["house"] == h:
                            insights.append(f"عبور {t_planet} في البيت {h}: {impact_text}")
                            
                        if r_lon is not None:
                            asp = get_aspect(t_data["lon"], r_lon, orb=8.0)
                            if asp:
                                insights.append(f"اتصال ({asp['name']}) بين {t_planet} العابر وحاكم البيت {h} ({r_name}): {asp['meaning']}")
                
                if not insights:
                    year_data[domain_key] = "استقرار وتناغم باطني عام؛ تتطور الأمور وفق مسارك الشخصي."
                else:
                    seen = set()
                    unique_insights = []
                    for ins in insights:
                        if ins not in seen:
                            seen.add(ins)
                            unique_insights.append(ins)
                    year_data[domain_key] = " <br><br> ".join(unique_insights)
                    
            forecasts.append(year_data)

        return forecasts

# ==========================================
# 5. واجهة تطبيق Streamlit والحسابات
# ==========================================
st.set_page_config(page_title="التحليل النجمي للميلادية", layout="wide")

st.title("🌟 نظام التحليل النفسي و الروحي النجمي للخارطة الميلادية")
st.write("وفق نظرية السباعية الروحية النجمية | تطوير الفلكي الدكتور ملهم احمد")

st.markdown("---")

with st.sidebar:
    st.header("📋 بيانات المولود")
    name = st.text_input("اسم الشخص:", "نجم")
    gender = st.selectbox("الجنس:", ["ذكر", "أنثى"])
    dob = st.date_input("تاريخ الميلاد:", value=datetime.date(1990, 1, 17), min_value=datetime.date(1900, 1, 1), max_value=datetime.date.today())
    tob = st.time_input("ساعة ودقيقة الميلاد:", datetime.time(11, 23), step=datetime.timedelta(minutes=1))

    selected_country = st.selectbox("دولة الميلاد:", country_list, index=country_list.index("Syria") if "Syria" in country_list else 0)
    country_code = country_map[selected_country]

    country_cities_data = cities_by_country.get(country_code, [])
    city_names = [city["name"] for city in country_cities_data]
    if not city_names:
        city_names = ["حماة"]

    default_city_idx = city_names.index("Hama") if "Hama" in city_names else 0
    selected_city_name = st.selectbox("مدينة الميلاد:", city_names, index=default_city_idx)
    submit = st.button("🚀 استخراج وتحليل الخارطة وفق النظرية الجديدة")

if submit and name and selected_city_name != "لا توجد بيانات مدن لهذه الدولة":
    city_data = next((city for city in country_cities_data if city["name"] == selected_city_name), None)

    if not city_data and country_cities_data:
        city_data = country_cities_data[0]

    if city_data:
        lat = city_data["latitude"]
        lng = city_data["longitude"]
        tz_str = tf.timezone_at(lng=lng, lat=lat) or "Asia/Damascus"

        jd = get_utc_julian_day(dob, tob, tz_str)

        engine = AstroEngine(jd, lat, lng)
        rulers_analysis = engine.analyze_house_rulers()
        psych_analyzer = DeepPsychologicalAnalyzer()
        forecast_report = engine.generate_3year_forecast()

        asc_sign = ZODIAC_SIGNS[engine.ascendant_sign_idx]

        st.success(f"تم حساب الخارطة النفسية و الروحية النجمية بنجاح لـ: **{name}** ({gender}) | الطالع: **{asc_sign}** ({engine.ascendant_deg % 30:.2f}°)")

        st.subheader("📊 1. مواضع الأجرام والكويكبات وفق السباعية الروحية")
        df_planets = pd.DataFrame([
            {
                "الجرم/الكويكب": p["body"],
                "البرج": p["sign"],
                "الدرجة": f"{p['degree']:.2f}°",
                "البيت": f"البيت {p['house']}",
                "الحالة": "متراجع ↺" if p["is_retro"] else "مستقيم ➔",
                "التصنيف": "كويكب نفسي" if p["is_asteroid"] else "جرم أساسي"
            } for p in engine.planets_data
        ])
        st.dataframe(df_planets, width='stretch')

        st.subheader("🏛️ 2. تحليل قوة حكام البيوت ومصادر الموارد والتقسيم الزمني")
        df_rulers = pd.DataFrame([
            {
                "البيت والتصنيف": f"البيت {r['house_num']} ({r['realm']})",
                "برج البيت": r["house_sign"],
                "حاكم البيت": r["ruler"],
                "موقع الحاكم": f"في {r['ruler_sign']} (البيت {r['ruler_house']})",
                "مصدر الموارد والدلالة الروحية": r["ruler_meaning"],
                "تقييم القوة": r["status"],
            } for r in rulers_analysis
        ])
        st.dataframe(df_rulers, width='stretch')

        st.markdown("##### 💡 تفاصيل مصادر الموارد والطاقة للبيوت بناءً على موقع الحاكم:")
        for r in rulers_analysis:
            with st.expander(f"🏠 <b>البيت {r['house_num']} ({r['house_sign']})</b> - حاكمه ({r['ruler']}) يقع في <b>البيت {r['ruler_house']}</b>", expanded=False):
                st.markdown(f"• <b>مصدر الموارد والتوجه:</b> {r['ruler_meaning']}")
                st.markdown(f"• <b>الوضع الفلكي:</b> {r['status']} (النقاط: {r['score']})")
                st.markdown(f"• <b>الأسباب والكرامات:</b> {' | '.join(r['reasons'])}")

        st.subheader("🧠 3. التحليل النفسي والروحي العميق (السباعية الروحية)")
        
        sign_counts = {}
        for p in engine.planets_data:
            s = p["sign"]
            sign_counts[s] = sign_counts.get(s, 0) + 1

        stelliums = {s: count for s, count in sign_counts.items() if count >= 3}
        if stelliums:
            for st_sign, count in stelliums.items():
                st.warning(
                    f"✨ <b>تمركز طاقي مكثف (Stellium) في برج {st_sign}:</b> تواجد {count} أجرام يفرز تركيزاً هائلاً على سمات هذا البرج."
                )

        placements_for_summary = [
            {"body": p["body"], "sign": p["sign"], "house": p["house"], "is_asteroid": p["is_asteroid"]}
            for p in engine.planets_data
        ]
        core_sum, psych_sum, spiritual_adv, integration_pl = psych_analyzer.generate_psychological_summary(
            placements_for_summary, stelliums
        )

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.info("🔥 **1. الجوهر والوعي النقي (فيستا وسيريس):**\n\n" + "\n\n".join(core_sum))
            st.warning("🦉 **2. الحكمة والتحول النفسي (بالاس وبلوتو):**\n\n" + ("\n\n".join(psych_sum) if psych_sum else "✔️ توازن طاقي باطني عام."))
        with col_p2:
            st.success("🪐 **3. توصيات الأجرام الفلكية العليا:**\n\n" + "\n\n".join(spiritual_adv))
            st.info("📋 **4. خطة التكامل والارتقاء الروحي:**\n\n" + "\n\n".join(integration_pl))

        st.markdown("##### 🔍 التشخيص النفسي التفصيلي لكل جرم في الخارطة:")
        for p in engine.planets_data:
            b_ar = p["body"]
            sign = p["sign"]
            house = p["house"]
            is_ast = p["is_asteroid"]

            with st.expander(f"📍 التحليل النفسي لـ {b_ar} في برج {sign} (البيت {house})"):
                rep = psych_analyzer.analyze_placement(body=b_ar, sign=sign, house=house, is_asteroid=is_ast)
                st.markdown(rep, unsafe_allow_html=True)

        if engine.aspects_data:
            st.markdown("##### 📐 شبكة الاتصالات الروحية والروابط الباطنية:")
            for asp in engine.aspects_data:
                b1 = asp["body1"]
                b2 = asp["body2"]
                h1 = asp["house1"]
                h2 = asp["house2"]
                asp_name = asp["aspect"]

                with st.expander(f"🔗 اتصال {asp_name} بين {b1} (البيت {h1}) و {b2} (البيت {h2})"):
                    rep_asp = psych_analyzer.analyze_aspect(body1=b1, body2=b2, aspect_name=asp_name, house1=h1, house2=h2)
                    st.markdown(rep_asp, unsafe_allow_html=True)

        st.subheader("🔮 4. التوقعات الروحية والمسار المستقبلي للثلاث سنوات القادمة")
        for f in forecast_report:
            with st.expander(f"📅 توقعات سنة {f['year']}"):
                st.write(f"✨ **النمو والارتقاء الروحي:** {f['spiritual_growth']}")
                st.write(f"❤ **الشراكات والاتصال الروحي:** {f['relationships_soul']}")
                st.write(f"🔥 **التحولات والبعث الباطني:** {f['transformation']}")
                st.write(f"💼 **الرسالة القدرية والإنجاز:** {f['career_mission']}")
                st.write(f"🌿 **الاستقرار النفسي والداخلي:** {f['inner_stability']}")

        # ==========================================
        # 6. إنشاء تقرير HTML الشامل المحدث والمدعوم كاملاً للطباعة
        # ==========================================
        html_rulers_rows = ""
        for r in rulers_analysis:
            badge_color = "#27ae60" if r["score"] >= 3 else ("#f39c12" if r["score"] >= 0 else "#e74c3c")
            html_rulers_rows += f"""
            <tr>
                <td><b>البيت {r['house_num']}</b> ({r['realm']})</td>
                <td>{r['house_sign']}</td>
                <td><b>{r['ruler']}</b></td>
                <td>{r['ruler_sign']} (البيت {r['ruler_house']})</td>
                <td style="text-align:right; font-size:12px;">{r['ruler_meaning']}</td>
                <td><span style="background-color:{badge_color}; color:white; padding:3px 8px; border-radius:4px; font-weight:bold;">{r['status']}</span></td>
            </tr>
            """

        html_rulers_detail = ""
        for r in rulers_analysis:
            html_rulers_detail += f"""
            <div class='card' style='border-right: 4px solid #8e44ad; margin-bottom:12px;'>
                <h4 style="margin-top:0; color: #2c3e50;">🏠 البيت {r['house_num']} ({r['house_sign']}) - حاكمه ({r['ruler']}) يقع في البيت {r['ruler_house']}</h4>
                <p style='font-size:14px; margin:5px 0;'><b>مصدر الموارد وتوجّه الطاقة:</b> {r['ruler_meaning']}</p>
                <p style='font-size:13px; margin:5px 0;'><b>تقييم القوة والوضع الفلكي:</b> {r['status']} (النقاط: {r['score']})</p>
                <p style='font-size:13px; margin:5px 0;'><b>الأسباب والكرامات:</b> {' | '.join(r['reasons'])}</p>
            </div>
            """

        html_bodies_detail = ""
        for p in engine.planets_data:
            b_ar = p["body"]
            sign = p["sign"]
            house = p["house"]
            is_ast = p["is_asteroid"]
            rep_text = psych_analyzer.analyze_placement(body=b_ar, sign=sign, house=house, is_asteroid=is_ast)
            html_bodies_detail += f"""
            <div class='card' style='border-right: 4px solid #2563eb; margin-bottom:12px;'>
                <h4 style="margin-top:0; color: #1e293b;">📍 {b_ar} في برج {sign} (البيت {house})</h4>
                <p style='font-size:13px; margin:5px 0;'>{rep_text}</p>
            </div>
            """

        html_aspects_detail = ""
        for asp in engine.aspects_data:
            b1 = asp["body1"]
            b2 = asp["body2"]
            h1 = asp["house1"]
            h2 = asp["house2"]
            asp_name = asp["aspect"]
            rep_asp = psych_analyzer.analyze_aspect(body1=b1, body2=b2, aspect_name=asp_name, house1=h1, house2=h2)
            html_aspects_detail += f"""
            <div class='card' style='border-right: 4px solid #16a34a; margin-bottom:12px;'>
                <h4 style="margin-top:0; color: #16a34a;">🔗 اتصال {asp_name} بين {b1} (البيت {h1}) و {b2} (البيت {h2})</h4>
                <p style='font-size:13px; margin:5px 0;'>{rep_asp}</p>
            </div>
            """

        html_forecast_cards = ""
        for f in forecast_report:
            html_forecast_cards += f"""
            <div class="card">
                <h3 style="color:#2980b9; margin-top:0;">📅 عام {f['year']}</h3>
                <p><b>✨ النمو والارتقاء الروحي:</b> {f['spiritual_growth']}</p>
                <p><b>❤️ الشراكات والاتصال الروحي:</b> {f['relationships_soul']}</p>
                <p><b>🔥 التحولات والبعث الباطني:</b> {f['transformation']}</p>
                <p><b>💼 الرسالة القدرية والإنجاز:</b> {f['career_mission']}</p>
                <p><b>🌿 الاستقرار النفسي والداخلي:</b> {f['inner_stability']}</p>
            </div>
            """

        html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>التقرير النفسي و الروحي النجمي - {name}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; color: #1e293b; padding: 20px; line-height: 1.6; }}
        .container {{ max-width: 950px; margin: auto; background: #ffffff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }}
        h1 {{ text-align: center; color: #0f172a; margin-bottom: 5px; }}
        .meta {{ text-align: center; color: #64748b; font-size: 14px; margin-bottom: 25px; }}
        h2 {{ color: #2563eb; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-top: 30px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #cbd5e1; padding: 10px; text-align: center; font-size: 13px; }}
        th {{ background-color: #1e293b; color: white; }}
        .card {{ background: #f1f5f9; border-right: 4px solid #2563eb; padding: 15px; border-radius: 6px; margin-bottom: 15px; }}
        .btn-print {{ display: block; width: 220px; margin: 30px auto; padding: 12px; background: #16a34a; color: white; text-align: center; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; }}
        @media print {{ .btn-print {{ display: none; }} body {{ padding:0; }} .container {{ box-shadow: none; max-width:100%; }} }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🌌 التقرير النفسي و الروحي النجمي (السباعية الروحية)</h1>
        <div class="meta">
            <b>الاسم:</b> {name} | <b>الجنس:</b> {gender} | <b>تاريخ الميلاد:</b> {dob} ({tob}) | <b>الموقع:</b> {selected_country} - {selected_city_name} | <b>برج الطالع:</b> {asc_sign}
        </div>

        <h2>🏛️ أولاً: تقييم قوة حكام البيوت ومصادر الموارد الباطنية</h2>
        <table>
            <thead>
                <tr>
                    <th>البيت والتصنيف</th>
                    <th>برج البيت</th>
                    <th>الحاكم</th>
                    <th>موقع الحاكم</th>
                    <th>مصدر الموارد والدلالة الروحية</th>
                    <th>القوة</th>
                </tr>
            </thead>
            <tbody>
                {html_rulers_rows}
            </tbody>
        </table>

        <h3>💡 تفاصيل مصادر الموارد والطاقة للبيوت بناءً على موقع الحاكم:</h3>
        {html_rulers_detail}

        <h2>🧠 ثانياً: التحليل النفسي والروحي العميق (السباعية الروحية)</h2>
        <div class="card" style="border-right-color: #8e44ad;">
            <h3 style="color:#8e44ad;">✨ 1. الجوهر والوعي النقي (فيستا وسيريس):</h3>
            <ul>{''.join([f"<li>{s}</li>" for s in core_sum])}</ul>

            <h3 style="color:#2980b9;">🪐 2. توصيات الأجرام الفلكية العليا:</h3>
            <ul>{''.join([f"<li>{s}</li>" for s in spiritual_adv])}</ul>

            <h3 style="color:#16a34a;">📋 3. خطة التكامل والارتقاء الروحي:</h3>
            <ul>{''.join([f"<li>{s}</li>" for s in integration_pl])}</ul>
        </div>

        <h3>🔍 التشخيص النفسي التفصيلي لكل جرم في الخارطة:</h3>
        {html_bodies_detail}

        <h3>📐 شبكة الاتصالات الروحية والروابط الباطنية:</h3>
        {html_aspects_detail}

        <h2>🔮 ثالثاً: التوقعات الروحية للثلاث سنوات القادمة</h2>
        {html_forecast_cards}

        <button class="btn-print" onclick="window.print()">🖨️ طباعة التقرير الشامل / حفظ PDF</button>
    </div>
</body>
</html>
"""

        st.markdown("---")
        st.subheader("📄 معاينة التقرير الجاهز للطباعة والتحميل")
        st.iframe(html_content, height=800)

        st.download_button(
            label="📥 تحميل التقرير كاملاً كملف HTML",
            data=html_content,
            file_name=f"Spiritual_Psychological_Report_{name}.html",
            mime="text/html"
        )