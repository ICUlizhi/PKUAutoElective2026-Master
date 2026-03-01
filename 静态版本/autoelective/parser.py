#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# filename: parser.py
# modified: 2019-09-09

import re
from lxml import etree
from .course import Course

_regexBzfxSida = re.compile(r'\?sida=(\S+?)&sttp=(?:bzx|bfx)')
_regexDigits = re.compile(r"\d+")


def get_tree_from_response(r):
    return etree.HTML(r.text) # 不要用 r.content, 否则可能会以 latin-1 编码

def get_tree(content):
    return etree.HTML(content)

def get_tables(tree):
    return tree.xpath('.//table//table[@class="datagrid"]')

def get_table_header(table):
    return [x.strip() for x in table.xpath('.//tr[@class="datagrid-header"]/th/text()') if x.strip()]

def get_table_trs(table):
    return table.xpath('.//tr[@class="datagrid-odd" or @class="datagrid-even"]')

def get_title(tree):
    title = tree.find('.//head/title')
    if title is None: # 双学位 sso_login 后先到 主修/辅双 选择页，这个页面没有 title 标签
        return None
    return title.text

def get_errInfo(tree):
    tds = tree.xpath(".//table//table//table//td")
    assert len(tds) == 1
    td = tds[0]
    strong = td.getchildren()[0]
    assert strong.tag == 'strong' and strong.text in ('出错提示:', '提示:')
    return "".join(td.xpath('./text()')).strip()

def get_tips(tree):
    tips = tree.xpath('.//td[@id="msgTips"]')
    if len(tips) == 0:
        return None
    td = tips[0].xpath('.//table//table//td')[1]
    return "".join(td.xpath('.//text()')).strip()

def get_sida(r):
    return _regexBzfxSida.search(r.text).group(1)

def get_courses(table):
    header = get_table_header(table)
    trs = get_table_trs(table)
    ixs = tuple(map(header.index, ["课程名","班号","开课单位"]))
    cs = []
    for tr in trs:
        t = tr.xpath('./th | ./td')
        name, class_no, school = map(lambda ix: t[ix].xpath('.//text()')[0], ixs)
        c = Course(name, class_no, school)
        cs.append(c)
    return cs

def get_courses_with_detail(table):
    header = get_table_header(table)
    trs = get_table_trs(table)

    base_fields = ("课程名", "班号", "开课单位")
    status_candidates = ("限数/已选", "限数/已选/候补")
    action_candidates = ("补选", "候补", "预选", "操作")

    missing_base = [name for name in base_fields if name not in header]
    if missing_base:
        raise ValueError(
            "Missing required columns: %s. header=%s" % (missing_base, header)
        )

    status_col = next((name for name in status_candidates if name in header), None)
    action_col = next((name for name in action_candidates if name in header), None)

    if status_col is None:
        raise ValueError(
            "Unable to locate status column (candidates=%s). header=%s" % (
                status_candidates, header
            )
        )
    if action_col is None:
        raise ValueError(
            "Unable to locate action column (candidates=%s). header=%s" % (
                action_candidates, header
            )
        )

    ixs = tuple(map(header.index, base_fields + (status_col, action_col)))
    cs = []
    for tr in trs:
        t = tr.xpath('./th | ./td')
        name, class_no, school = map(lambda ix: t[ix].xpath('.//text()')[0], ixs[:3])

        status_text = "".join(t[ixs[3]].xpath('.//text()')).strip()
        status_nums = tuple(map(int, _regexDigits.findall(status_text)))
        if len(status_nums) not in (2, 3):
            raise ValueError(
                "Unexpected status format %r for course(%s,%s,%s), expected 2 or 3 numbers" % (
                    status_text, name, class_no, school
                )
            )

        hrefs = t[ixs[4]].xpath('.//a/@href')
        texts = [x.strip() for x in t[ixs[4]].xpath('.//a//text()') if x.strip()]
        href = hrefs[0] if len(hrefs) > 0 else None
        action_text = texts[0] if len(texts) > 0 else "".join(t[ixs[4]].xpath('.//text()')).strip()
        c = Course(name, class_no, school, status_nums, href, action_text)
        cs.append(c)
    return cs
