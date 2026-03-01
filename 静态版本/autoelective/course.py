#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# filename: course.py
# modified: 2019-09-08

class Course(object):

    __slots__ = ['_name','_class_no','_school','_status','_href','_action_text','_ident']

    def __init__(self, name, class_no, school, status=None, href=None, action_text=None):
        self._name = name
        self._class_no = int(class_no) # 确保 01 与 1 为同班号，因为表格软件将 01 视为 1
        self._school = school
        self._status = status # (maxi, used) 或 (maxi, used, waiting)
        self._href = href     # 选课链接
        self._action_text = action_text  # 补选/候补/预选/...
        self._ident = (self._name, self._class_no, self._school)

    @property
    def name(self):
        return self._name

    @property
    def class_no(self):
        return self._class_no

    @property
    def school(self):
        return self._school

    @property
    def status(self):
        return self._status

    @property
    def href(self):
        return self._href

    @property
    def action_text(self):
        return self._action_text

    @property
    def max_quota(self):
        assert self._status is not None
        return self._status[0]

    @property
    def used_quota(self):
        assert self._status is not None
        return self._status[1]

    @property
    def remaining_quota(self):
        assert self._status is not None
        maxi, used = self._status[0], self._status[1]
        return maxi - used

    def is_available(self):
        assert self._status is not None
        maxi, used = self._status[0], self._status[1]
        return maxi > used

    def is_action_available(self):
        return bool(self._href)

    def to_simplified(self):
        return Course(self._name, self._class_no, self._school)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return self._ident == other._ident

    def __hash__(self):
        return hash(self._ident)

    def __repr__(self):
        if self._status is not None:
            status = " / ".join(map(str, self._status))
            if self._action_text:
                return "%s(%s, %s, %s, %s, action=%s)" % (
                    self.__class__.__name__,
                    self._name, self._class_no, self._school, status, self._action_text,
                )
            return "%s(%s, %s, %s, %s)" % (
                self.__class__.__name__,
                self._name, self._class_no, self._school, status,
            )
        else:
            return "%s(%s, %s, %s)" % (
                self.__class__.__name__,
                self._name, self._class_no, self._school,
            )
