#!/usr/bin/env python3
"""Add the command-bar translation keys to every locale, preserving parity.

The English source of truth defines the key set and the interpolation
variables; each locale gets a hand-written translation for the strings we
have, and falls back to English for the ones we do not (the UI reads them
through i18next with a `defaultValue`, so the fallback is always safe).
"""
import json
import io
import os

LOCALES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "i18n", "locales",
)

TRANSLATIONS = {
    "en": {
        "commandSearch": "Search workspace",
        "commandEmpty": "No matching surfaces.",
        "systemStatus": "Workspace services",
        "systemOnline": "Online",
        "workspace": "Workspace",
    },
    "zh-CN": {
        "commandSearch": "搜索工作区",
        "commandEmpty": "没有匹配的面板。",
        "systemStatus": "工作区服务",
        "systemOnline": "在线",
        "workspace": "工作区",
    },
    "ja": {
        "commandSearch": "ワークスペースを検索",
        "commandEmpty": "一致する画面がありません。",
        "systemStatus": "ワークスペースサービス",
        "systemOnline": "オンライン",
        "workspace": "ワークスペース",
    },
    "ko": {
        "commandSearch": "워크스페이스 검색",
        "commandEmpty": "일치하는 화면이 없습니다.",
        "systemStatus": "워크스페이스 서비스",
        "systemOnline": "온라인",
        "workspace": "워크스페이스",
    },
    "ar": {
        "commandSearch": "ابحث في مساحة العمل",
        "commandEmpty": "لا توجد شاشات مطابقة.",
        "systemStatus": "خدمات مساحة العمل",
        "systemOnline": "متصل",
        "workspace": "مساحة العمل",
    },
    "fa": {
        "commandSearch": "جستجو در فضای کاری",
        "commandEmpty": "هیچ صفحه‌ای مطابقت ندارد.",
        "systemStatus": "سرویس‌های فضای کاری",
        "systemOnline": "برخط",
        "workspace": "فضای کاری",
    },
    "es": {
        "commandSearch": "Buscar en el espacio de trabajo",
        "commandEmpty": "No hay paneles coincidentes.",
        "systemStatus": "Servicios del espacio de trabajo",
        "systemOnline": "En línea",
        "workspace": "Espacio de trabajo",
    },
    "de": {
        "commandSearch": "Arbeitsbereich durchsuchen",
        "commandEmpty": "Keine passenden Ansichten.",
        "systemStatus": "Arbeitsbereich-Dienste",
        "systemOnline": "Online",
        "workspace": "Arbeitsbereich",
    },
    "pt-BR": {
        "commandSearch": "Buscar no espaço de trabalho",
        "commandEmpty": "Nenhuma tela correspondente.",
        "systemStatus": "Serviços do espaço de trabalho",
        "systemOnline": "Online",
        "workspace": "Espaço de trabalho",
    },
    "id": {
        "commandSearch": "Cari di ruang kerja",
        "commandEmpty": "Tidak ada panel yang cocok.",
        "systemStatus": "Layanan ruang kerja",
        "systemOnline": "Online",
        "workspace": "Ruang kerja",
    },
    "tr": {
        "commandSearch": "Çalışma alanında ara",
        "commandEmpty": "Eşleşen panel yok.",
        "systemStatus": "Çalışma alanı hizmetleri",
        "systemOnline": "Çevrimiçi",
        "workspace": "Çalışma alanı",
    },
    "vi": {
        "commandSearch": "Tìm trong không gian làm việc",
        "commandEmpty": "Không có bảng điều khiển phù hợp.",
        "systemStatus": "Dịch vụ không gian làm việc",
        "systemOnline": "Trực tuyến",
        "workspace": "Không gian làm việc",
    },
}


def main() -> None:
    for code, additions in TRANSLATIONS.items():
        path = os.path.join(LOCALES_DIR, f"{code}.json")
        with io.open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        layout = data.setdefault("layout", {})
        for key, value in additions.items():
            layout[key] = value
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"updated {code}")


if __name__ == "__main__":
    main()
