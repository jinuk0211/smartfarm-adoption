"""Presentation helpers for the farmer-facing planning interface."""

from html import escape

import streamlit as st


def section(eyebrow: str, title: str, detail: str = "") -> None:
    st.markdown(
        f'<div class="section-head"><p class="eyebrow">{escape(eyebrow)}</p>'
        f'<h2>{escape(title)}</h2><p class="section-detail">{escape(detail)}</p></div>',
        unsafe_allow_html=True,
    )


def stat(label: str, value: str, note: str, *, emphasis: bool = False) -> None:
    style = "stat-block emphasis" if emphasis else "stat-block"
    st.markdown(
        f'<div class="{style}"><p class="stat-label">{escape(label)}</p>'
        f'<p class="stat-value">{escape(value)}</p><p class="stat-note">{escape(note)}</p></div>',
        unsafe_allow_html=True,
    )


def takeaway(title: str, detail: str) -> None:
    st.markdown(
        f'<div class="takeaway"><strong>{escape(title)}</strong>'
        f'<p>{escape(detail)}</p></div>', unsafe_allow_html=True,
    )


def apply_style() -> None:
    st.markdown("""<style>
    :root {--ink:#193d2e; --muted:#647267; --paper:#f7f5ee; --line:#d9dfd3; --accent:#b96b36;}
    .stApp {background:var(--paper); color:var(--ink);}
    .stApp,button,input,select {font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;}
    .block-container {max-width:1230px; padding:1.6rem 2.8rem 4rem;}
    header[data-testid="stHeader"] {background:transparent; height:1rem;}
    [data-testid="stToolbar"] {opacity:.45;}
    [data-testid="stAppDeployButton"] {display:none;}
    [data-testid="stMainMenu"] {opacity:.45;}
    h1,h2,h3,h4 {color:var(--ink); letter-spacing:-.055em; font-weight:700;}
    h1 {font-size:2.3rem!important; line-height:1.3!important;}
    h2 {font-size:1.8rem!important; line-height:1.35!important; padding-top:0!important;}
    h3 {font-size:1.18rem!important; line-height:1.5!important;}
    p,li {line-height:1.7;}
    .brand {display:flex;justify-content:space-between;align-items:center;padding:0 0 20px;border-bottom:1px solid var(--line);margin-bottom:10px;}
    .brand strong {font-size:19px;letter-spacing:-.05em;}
    .brand span {font-size:12px;color:var(--muted);letter-spacing:.12em;}
    [data-baseweb="tab-list"] {gap:30px;border-bottom:1px solid var(--line);padding-top:3px;}
    [data-baseweb="tab"] {font-size:15px;font-weight:600;padding:16px 0;height:auto;color:#667366;}
    [data-baseweb="tab"][aria-selected="true"] {color:var(--ink);}
    [data-baseweb="tab-highlight"] {background:#245b3f; height:3px;}
    [role="tablist"] {gap:28px!important;}
    [data-testid="stTab"] p {font-size:15px;font-weight:600;}
    [data-testid="stTab"][aria-selected="true"] {color:#245b3f!important;}
    [data-testid="stTab"] .react-aria-SelectionIndicator {background-color:#245b3f!important;}
    [data-baseweb="tab-panel"] {padding-top:24px;}
    .eyebrow {font-size:12px!important;letter-spacing:.12em;color:#617b64;margin:0 0 14px!important;font-weight:700;}
    .hero-title {font-size:49px!important;line-height:1.27!important;letter-spacing:-.065em;margin:0 0 18px!important;max-width:720px;}
    .hero-title em {font-style:normal;color:#a35c2f;}
    .hero-description {font-size:17px;color:#536657;max-width:620px;margin:0 0 18px;}
    .home-hero {background-size:cover;background-position:center;min-height:294px;padding-top:10px;margin-bottom:4px;}
    .section-head {margin:6px 0 18px;}
    .section-head .eyebrow {margin-bottom:8px!important;}
    .section-head h2 {margin-bottom:7px;}
    .section-detail {color:#617164;font-size:15px;max-width:800px;}
    .stat-block {padding:20px 0 12px;border-top:1px solid #cad5c5;min-height:125px;}
    .stat-label {font-size:14px;color:#4c6754;margin:0 0 8px!important;}
    .stat-value {font-size:38px!important;line-height:1.2!important;letter-spacing:-.065em;font-weight:700;margin:0 0 10px!important;color:var(--ink);}
    .stat-note {font-size:12px;color:#637266;margin:0!important;line-height:1.6!important;}
    .emphasis .stat-value {color:#a65d30;}
    .takeaway {border-left:3px solid #b87743;padding:12px 20px;margin:8px 0 18px;background:#f1ede1;}
    .takeaway strong {font-size:17px;letter-spacing:-.025em;}
    .takeaway p {font-size:14px;color:#59685b;margin:6px 0 0;}
    .example-heading {display:flex;justify-content:space-between;align-items:center;margin:18px 0 12px;}
    .example-heading strong {font-size:19px;letter-spacing:-.04em;}
    .example-heading span {font-size:12px;color:#797965;}
    .journey {display:flex;gap:28px;border-top:1px solid var(--line);padding-top:18px;margin-top:12px;}
    .journey p {flex:1;margin:0;font-size:14px;color:#657465;}
    .journey b {display:block;color:#284f36;font-size:15px;margin-bottom:3px;}
    button[kind="primary"] {background:#23553a;border:1px solid #23553a;border-radius:6px;min-height:46px;padding:7px 22px;font-weight:600;}
    button[kind="secondary"] {border-color:#cbd4c5;border-radius:6px;background:transparent;min-height:42px;}
    [data-testid="stDownloadButton"] button {font-size:13px;}
    [data-testid="stMetric"] {border:none;background:transparent;padding:10px 0;}
    [data-testid="stMetricLabel"] {color:#5b6d5d;font-size:13px;}
    [data-testid="stMetricValue"] {font-size:28px;letter-spacing:-.04em;}
    [data-testid="stExpander"] {border:1px solid #d6dfd0;border-radius:6px;background:#fcfcf8;box-shadow:none;}
    [data-testid="stExpander"] summary {font-size:15px;min-height:49px;}
    [data-testid="stExpander"] details>div {padding:12px 22px 22px;}
    [data-testid="stCaptionContainer"] {font-size:12px!important;color:#68776a;line-height:1.6;}
    [data-testid="stCaptionContainer"] p {color:#465448!important;font-size:13px!important;line-height:1.75;opacity:1;}
    [data-testid="stAlert"] {font-size:14px;border-radius:4px;}
    [data-testid="stWidgetLabel"] p {font-size:14px;font-weight:500;}
    [data-baseweb="select"]>div, [data-baseweb="input"] {background:#fffef9;border-color:#d3dccd;border-radius:5px;}
    hr {margin:1.8rem 0;border-color:var(--line);}
    @media(max-width:750px) {
      .block-container {padding:1.2rem 1.1rem 3rem;}
      .hero-title {font-size:35px!important;}
      .home-hero {background-image:none!important;min-height:0;}
      .stat-value {font-size:31px!important;}
      [data-baseweb="tab-list"] {gap:20px;}
      [role="tablist"] {gap:20px!important;}
      .journey {gap:14px;flex-wrap:wrap;}.journey p {min-width:130px;}
      .brand span {display:none;}.example-heading {display:block;}
      .example-heading span {display:block;margin-top:8px;line-height:1.7;}
    }
    </style>""", unsafe_allow_html=True)
