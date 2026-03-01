#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# filename: loop.py
# modified: 2021-09-11

import os
import time
import random
import urllib.request
import subprocess
from queue import Queue, Empty
from collections import deque
from itertools import combinations
from requests.compat import json
from requests.exceptions import RequestException
import numpy as np
from . import __version__, __date__
from .environ import Environ
from .config import AutoElectiveConfig
from .logger import ConsoleLogger, FileLogger
from .course import Course
from .captcha import CaptchaRecognizer
from .parser import get_tables, get_courses, get_courses_with_detail, get_sida
from .hook import _dump_request
from .iaaa import IAAAClient
from .elective import ElectiveClient
from .const import CAPTCHA_CACHE_DIR, USER_AGENT_LIST, WEB_LOG_DIR, CNN_MODEL_FILE
from .exceptions import *
from ._internal import mkdir

environ = Environ()
config = AutoElectiveConfig()
cout = ConsoleLogger("loop")
ferr = FileLogger("loop.error") # loop 的子日志，同步输出到 console

username = config.iaaa_id
password = config.iaaa_password
is_dual_degree = config.is_dual_degree
identity = config.identity
refresh_interval = config.refresh_interval
refresh_random_deviation = config.refresh_random_deviation
supply_cancel_page = config.supply_cancel_page
iaaa_client_timeout = config.iaaa_client_timeout
elective_client_timeout = config.elective_client_timeout
login_loop_interval = config.login_loop_interval
elective_client_pool_size = config.elective_client_pool_size
elective_client_max_life = config.elective_client_max_life
is_print_mutex_rules = config.is_print_mutex_rules

config.check_identify(identity)
config.check_supply_cancel_page(supply_cancel_page)

_USER_WEB_LOG_DIR = os.path.join(WEB_LOG_DIR, config.get_user_subpath())
mkdir(_USER_WEB_LOG_DIR)
ROTATE_STATE_FILE = os.environ.get(
    "ROTATE_SNAT_STATE_FILE",
    "/home/ubuntu/work/skj/.rotate_snat_state.prod.json",
)

recognizer = CaptchaRecognizer(CNN_MODEL_FILE)
# recognizer = Chaojiying_Client('flyingpig', 'chaojiying', '929137')

electivePool = Queue(maxsize=elective_client_pool_size)
reloginPool = Queue(maxsize=elective_client_pool_size)

goals = environ.goals  # let N = len(goals);
ignored = environ.ignored
mutexes = np.zeros(0, dtype=np.uint8) # uint8 [N][N];
delays = np.zeros(0, dtype=np.int) # int [N];

killedElective = ElectiveClient(-1)
NO_DELAY = -1
_ROTATE_SNAT_SCRIPT = os.environ.get("ROTATE_SNAT_SCRIPT", "/home/ubuntu/work/skj/rotate_snat_cron.sh")
_ROTATE_ON_LOOP_END = os.environ.get("ROTATE_ON_LOOP_END", "1").lower() in ("1", "true", "yes", "on")
_ROTATE_MIN_INTERVAL_SECONDS = float(os.environ.get("ROTATE_MIN_INTERVAL_SECONDS", "300"))
_LOOP_MODE = os.environ.get("LOOP_MODE", "normal").strip().lower()
_INSPECT_ONLY_MODE = _LOOP_MODE in ("inspect_only", "observe", "monitor")


class _ElectiveNeedsLogin(Exception):
    pass

class _ElectiveExpired(Exception):
    pass


def _get_refresh_interval():
    if refresh_random_deviation <= 0:
        return refresh_interval
    delta = (random.random() * 2 - 1) * refresh_random_deviation * refresh_interval
    return refresh_interval + delta

def _ignore_course(course, reason):
    ignored[course.to_simplified()] = reason

def _add_error(e):
    clz = e.__class__
    name = clz.__name__
    key = "[%s] %s" % (e.code, name) if hasattr(clz, "code") else name
    environ.errors[key] += 1

def _format_timestamp(timestamp):
    if timestamp == -1:
        return str(timestamp)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

def _dump_respose_content(content, filename):
    path = os.path.join(_USER_WEB_LOG_DIR, filename)
    with open(path, 'wb') as fp:
        fp.write(content)


def _get_course_page_mode(courses):
    if len(courses) == 0:
        return "unknown"
    # status has 3 fields on preselect page: 限数/已选/候补
    if any(c.status is not None and len(c.status) == 3 for c in courses):
        return "preselect"
    if all(c.status is not None and len(c.status) == 2 for c in courses):
        return "normal"
    return "unknown"


def _get_rotated_ip_from_state():
    if not os.path.exists(ROTATE_STATE_FILE):
        return ""
    try:
        with open(ROTATE_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.loads(f.read())
        return str(state.get("last_eip", "")).strip()
    except Exception:
        return ""


def _get_egress_ip_live(timeout=2.0):
    urls = [
        "https://ifconfig.me/ip",
        "https://ipv4.icanhazip.com",
    ]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for url in urls:
        try:
            with opener.open(url, timeout=timeout) as resp:
                ip = resp.read().decode("utf-8", errors="ignore").strip()
                if ip:
                    return ip
        except Exception:
            continue
    return ""


def _get_last_rotate_timestamp():
    if not os.path.exists(ROTATE_STATE_FILE):
        return 0
    try:
        with open(ROTATE_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.loads(f.read())
        return int(state.get("updated_at", 0) or 0)
    except Exception:
        return 0


def _drain_queue(q):
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except Empty:
            break
    return items


def _reset_client_sessions():
    ep_items = _drain_queue(electivePool)
    rp_items = _drain_queue(reloginPool)

    reset_targets = []
    keep_rp_items = []
    for item in ep_items:
        if item is not killedElective:
            reset_targets.append(item)
    for item in rp_items:
        if item is killedElective:
            keep_rp_items.append(item)
        else:
            reset_targets.append(item)

    for client in reset_targets:
        try:
            client.clear_cookies()
            client.set_expired_time(-1)
            client.reset_session()
        except Exception as e:
            ferr.error(e)
            cout.warning("Failed to reset client %s" % getattr(client, "id", "?"))

    for item in ep_items:
        electivePool.put_nowait(item)
    for item in keep_rp_items:
        reloginPool.put_nowait(item)
    for item in rp_items:
        if item is not killedElective:
            reloginPool.put_nowait(item)


def _rotate_ip_on_loop_end():
    if not _ROTATE_ON_LOOP_END:
        return

    now = int(time.time())
    last_ts = _get_last_rotate_timestamp()
    cooldown_left = int(_ROTATE_MIN_INTERVAL_SECONDS - (now - last_ts))
    should_rotate_now = environ.rotate_pending or (last_ts <= 0) or (cooldown_left <= 0)
    if not should_rotate_now:
        cout.info("Skip IP rotate this loop: cooldown %ss left" % cooldown_left)
        return

    if environ.iaaa_busy:
        environ.rotate_pending = True
        cout.info("Defer IP rotate this loop: IAAA thread busy")
        return

    _reset_client_sessions()
    ok = _run_rotate_command(log_prefix="IP rotate result")
    environ.rotate_pending = not ok


def _run_rotate_command(log_prefix="IP rotate result"):
    try:
        r = subprocess.run(
            ["/bin/bash", "-lc", _ROTATE_SNAT_SCRIPT],
            timeout=25,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as e:
        ferr.error(e)
        cout.warning("%s: rotate command failed to execute" % log_prefix)
        return False

    if r.returncode != 0:
        ferr.error("%s failed with code %s, stderr=%s" % (log_prefix, r.returncode, (r.stderr or "").strip()))
        cout.warning("%s failed (code=%s)" % (log_prefix, r.returncode))
        return False

    output = [x for x in (r.stdout or "").splitlines() if x.strip()]
    if output:
        cout.info("%s: %s" % (log_prefix, output[-1]))
    else:
        cout.info("%s: success" % log_prefix)
    return True


def _is_emergency_network_error(e):
    msg = str(e).lower()
    # Treat upstream connect/TLS failures on both IAAA and elective host as
    # emergency signals: the current egress path may be unhealthy.
    if ("iaaa.pku.edu.cn" not in msg) and ("elective.pku.edu.cn" not in msg):
        return False
    keywords = (
        "max retries exceeded",
        "ssleoferror",
        "eof occurred in violation of protocol",
        "wrong version number",
        "connection reset",
        "connection refused",
        "failed to establish a new connection",
        "tlsv1",
    )
    return any(k in msg for k in keywords)


def _emergency_rotate_ip(reason):
    ferr.critical("[EMERGENCY_IP_ROTATE] %s" % reason)
    cout.error("[EMERGENCY] %s" % reason)
    # Mark pending first to ensure next loop still rotates even if this immediate attempt fails.
    environ.rotate_pending = True
    ok = _run_rotate_command(log_prefix="Emergency IP rotate")
    if ok:
        environ.rotate_pending = False


def _log_loop_behavior(behavior, rotated_ip="", live_ip="", extra=""):
    msg = "mode=%s behavior=%s rotated_ip=%s live_ip=%s %s" % (
        _LOOP_MODE,
        behavior,
        rotated_ip or "-",
        live_ip or "-",
        extra.strip(),
    )
    cout.info("Loop behavior: %s" % msg)
    ferr.warning("[loop_behavior] %s" % msg)


def run_iaaa_loop():

    elective = None

    while True:

        if elective is None:
            elective = reloginPool.get()
            if elective is killedElective:
                cout.info("Quit IAAA loop")
                return
            environ.iaaa_busy = True

        environ.iaaa_loop += 1
        user_agent = random.choice(USER_AGENT_LIST)

        cout.info("Try to login IAAA (client: %s)" % elective.id)
        cout.info("User-Agent: %s" % user_agent)

        try:

            iaaa = IAAAClient(timeout=iaaa_client_timeout) # not reusable
            iaaa.set_user_agent(user_agent)

            # request elective's home page to get cookies
            r = iaaa.oauth_home()

            r = iaaa.oauth_login(username, password)

            try:
                token = r.json()["token"]
            except Exception as e:
                ferr.error(e)
                raise OperationFailedError(msg="Unable to parse IAAA token. response body: %s" % r.content)

            elective.clear_cookies()
            elective.set_user_agent(user_agent)

            r = elective.sso_login(token)

            if is_dual_degree:
                sida = get_sida(r)
                sttp = identity
                referer = r.url
                r = elective.sso_login_dual_degree(sida, sttp, referer)

            if elective_client_max_life == -1:
                elective.set_expired_time(-1)
            else:
                elective.set_expired_time(int(time.time()) + elective_client_max_life)

            cout.info("Login success (client: %s, expired_time: %s)" % (
                      elective.id, _format_timestamp(elective.expired_time)))
            cout.info("")

            electivePool.put_nowait(elective)
            elective = None
            environ.iaaa_busy = False

        except (ServerError, StatusCodeError) as e:
            ferr.error(e)
            cout.warning("ServerError/StatusCodeError encountered")
            _add_error(e)

        except OperationFailedError as e:
            ferr.error(e)
            cout.warning("OperationFailedError encountered")
            _add_error(e)

        except RequestException as e:
            ferr.error(e)
            cout.warning("RequestException encountered")
            _add_error(e)
            # IAAA loop only sees network-layer request failures; rotate immediately
            # to avoid burning time on a broken egress path.
            if not _INSPECT_ONLY_MODE:
                _emergency_rotate_ip("IAAA loop RequestException detected, rotate IP immediately")

        except IAAAIncorrectPasswordError as e:
            cout.error(e)
            _add_error(e)
            raise e

        except IAAAForbiddenError as e:
            ferr.error(e)
            _add_error(e)
            raise e

        except IAAAException as e:
            ferr.error(e)
            cout.warning("IAAAException encountered")
            _add_error(e)

        except CaughtCheatingError as e:
            ferr.critical(e) # 严重错误
            _add_error(e)
            raise e

        except ElectiveException as e:
            ferr.error(e)
            cout.warning("ElectiveException encountered")
            _add_error(e)

        except json.JSONDecodeError as e:
            ferr.error(e)
            cout.warning("JSONDecodeError encountered")
            _add_error(e)

        except KeyboardInterrupt as e:
            raise e

        except Exception as e:
            ferr.exception(e)
            _add_error(e)
            raise e

        finally:
            if elective is None:
                environ.iaaa_busy = False
            t = login_loop_interval
            cout.info("")
            cout.info("IAAA login loop sleep %s s" % t)
            cout.info("")
            time.sleep(t)


def run_elective_loop():

    elective = None
    noWait = False

    ## load courses

    cs = config.courses  # OrderedDict
    N = len(cs)
    cid_cix = {} # { cid: cix }

    for ix, (cid, c) in enumerate(cs.items()):
        goals.append(c)
        cid_cix[cid] = ix

    ## load mutex

    ms = config.mutexes
    mutexes.resize((N, N), refcheck=False)

    for mid, m in ms.items():
        ixs = []
        for cid in m.cids:
            if cid not in cs:
                raise UserInputException("In 'mutex:%s', course %r is not defined" % (mid, cid))
            ix = cid_cix[cid]
            ixs.append(ix)
        for ix1, ix2 in combinations(ixs, 2):
            mutexes[ix1, ix2] = mutexes[ix2, ix1] = 1

    ## load delay

    ds = config.delays
    delays.resize(N, refcheck=False)
    delays.fill(NO_DELAY)

    for did, d in ds.items():
        cid = d.cid
        if cid not in cs:
            raise UserInputException("In 'delay:%s', course %r is not defined" % (did, cid))
        ix = cid_cix[cid]
        delays[ix] = d.threshold

    ## setup elective pool

    for ix in range(1, elective_client_pool_size + 1):
        client = ElectiveClient(id=ix, timeout=elective_client_timeout)
        client.set_user_agent(random.choice(USER_AGENT_LIST))
        electivePool.put_nowait(client)

    ## print header

    header = "# PKU Auto-Elective Tool v%s (%s) #" % (__version__, __date__)
    line = "#" + "-" * (len(header) - 2) + "#"

    cout.info(line)
    cout.info(header)
    cout.info(line)
    cout.info("")

    line = "-" * 30

    cout.info("> User Agent")
    cout.info(line)
    cout.info("pool_size: %d" % len(USER_AGENT_LIST))
    cout.info(line)
    cout.info("")
    cout.info("> Config")
    cout.info(line)
    cout.info("is_dual_degree: %s" % is_dual_degree)
    cout.info("identity: %s" % identity)
    cout.info("refresh_interval: %s" % refresh_interval)
    cout.info("refresh_random_deviation: %s" % refresh_random_deviation)
    cout.info("supply_cancel_page: %s" % supply_cancel_page)
    cout.info("iaaa_client_timeout: %s" % iaaa_client_timeout)
    cout.info("elective_client_timeout: %s" % elective_client_timeout)
    cout.info("login_loop_interval: %s" % login_loop_interval)
    cout.info("elective_client_pool_size: %s" % elective_client_pool_size)
    cout.info("elective_client_max_life: %s" % elective_client_max_life)
    cout.info("is_print_mutex_rules: %s" % is_print_mutex_rules)
    cout.info("loop_mode: %s" % _LOOP_MODE)
    cout.info("rotate_min_interval_seconds: %s" % _ROTATE_MIN_INTERVAL_SECONDS)
    cout.info(line)
    cout.info("")

    while True:

        noWait = False

        if elective is None:
            elective = electivePool.get()

        environ.elective_loop += 1

        cout.info("")
        cout.info("======== Loop %d ========" % environ.elective_loop)
        cout.info("")

        ## print current plans

        current = [ c for c in goals if c not in ignored ]
        if len(current) > 0:
            cout.info("> Current tasks")
            cout.info(line)
            for ix, course in enumerate(current):
                cout.info("%02d. %s" % (ix + 1, course))
            cout.info(line)
            cout.info("")

        ## print ignored course

        if len(ignored) > 0:
            cout.info("> Ignored tasks")
            cout.info(line)
            for ix, (course, reason) in enumerate(ignored.items()):
                cout.info("%02d. %s  %s" % (ix + 1, course, reason))
            cout.info(line)
            cout.info("")

        ## print mutex rules

        if np.any(mutexes):
            cout.info("> Mutex rules")
            cout.info(line)
            ixs = [ (ix1, ix2) for ix1, ix2 in np.argwhere( mutexes == 1 ) if ix1 < ix2 ]
            if is_print_mutex_rules:
                for ix, (ix1, ix2) in enumerate(ixs):
                    cout.info("%02d. %s --x-- %s" % (ix + 1, goals[ix1], goals[ix2]))
            else:
                cout.info("%d mutex rules" % len(ixs))
            cout.info(line)
            cout.info("")

        ## print delay rules

        if np.any( delays != NO_DELAY ):
            cout.info("> Delay rules")
            cout.info(line)
            ds = [ (cix, threshold) for cix, threshold in enumerate(delays) if threshold != NO_DELAY ]
            for ix, (cix, threshold) in enumerate(ds):
                cout.info("%02d. %s --- %d" % (ix + 1, goals[cix], threshold))
            cout.info(line)
            cout.info("")

        rotated_ip = _get_rotated_ip_from_state()
        live_ip = _get_egress_ip_live()
        if rotated_ip:
            cout.info("> Rotated egress IP: %s" % rotated_ip)
        if live_ip:
            cout.info("> Live egress IP: %s" % live_ip)
        if environ.rotate_pending and not environ.iaaa_busy:
            cout.info("Pending IP rotate detected, rotating now")
            _rotate_ip_on_loop_end()

        if len(current) == 0 and not _INSPECT_ONLY_MODE:
            cout.info("No tasks")
            cout.info("Quit elective loop")
            reloginPool.put_nowait(killedElective) # kill signal
            return
        elif len(current) == 0 and _INSPECT_ONLY_MODE:
            cout.info("No tasks (inspect_only mode still running)")

        ## print client info

        cout.info("> Current client: %s (qsize: %s)" % (elective.id, electivePool.qsize() + 1))
        cout.info("> Client expired time: %s" % _format_timestamp(elective.expired_time))
        cout.info("User-Agent: %s" % elective.user_agent)
        cout.info("")

        try:

            if not elective.has_logined:
                raise _ElectiveNeedsLogin  # quit this loop

            if elective.is_expired:
                try:
                    cout.info("Logout")
                    r = elective.logout()
                except Exception as e:
                    cout.warning("Logout error")
                    cout.exception(e)
                raise _ElectiveExpired   # quit this loop

            ## check supply/cancel page

            page_r = None

            if supply_cancel_page == 1:

                cout.info("Get SupplyCancel page %s" % supply_cancel_page)

                r = page_r = elective.get_SupplyCancel(username)
                tables = get_tables(r._tree)
                try:
                    elected = get_courses(tables[1])
                    plans = get_courses_with_detail(tables[0])
                except Exception as e:
                    filename = "elective.get_SupplyCancel_%d.html" % int(time.time() * 1000)
                    _dump_respose_content(r.content, filename)
                    cout.info("Page dump to %s" % filename)
                    raise UnexceptedHTMLFormat(msg="unable to parse SupplyCancel: %s" % e)

            else:
                #
                # 刷新非第一页的课程，第一次请求会遇到返回空页面的情况
                #
                # 模拟方法：
                # 1.先登录辅双，打开补退选第二页
                # 2.再在同一浏览器登录主修
                # 3.刷新辅双的补退选第二页可以看到
                #
                # -----------------------------------------------
                #
                # 引入 retry 逻辑以防止以为某些特殊原因无限重试
                # 正常情况下一次就能成功，但是为了应对某些偶发错误，这里设为最多尝试 3 次
                #
                retry = 3
                while True:
                    if retry == 0:
                        raise OperationFailedError(msg="unable to get normal Supplement page %s" % supply_cancel_page)

                    cout.info("Get Supplement page %s" % supply_cancel_page)
                    r = page_r = elective.get_supplement(username, page=supply_cancel_page) # 双学位第二页
                    tables = get_tables(r._tree)
                    try:
                        elected = get_courses(tables[1])
                        plans = get_courses_with_detail(tables[0])
                    except IndexError as e:
                        cout.warning("IndexError encountered")
                        cout.info("Get SupplyCancel first to prevent empty table returned")
                        _ = elective.get_SupplyCancel(username) # 遇到空页面时请求一次补退选主页，之后就可以不断刷新
                    except Exception as e:
                        filename = "elective.get_supplement_%d.html" % int(time.time() * 1000)
                        _dump_respose_content(r.content, filename)
                        cout.info("Page dump to %s" % filename)
                        raise UnexceptedHTMLFormat(msg="unable to parse Supplement page: %s" % e)
                    else:
                        break
                    finally:
                        retry -= 1

            mode = _get_course_page_mode(plans)
            cout.info("Detected page mode: %s" % mode)
            if mode == "unknown":
                raise UnexceptedHTMLFormat(msg="unknown course page mode, status lens=%s" % (
                    [len(c.status) if c.status is not None else None for c in plans]
                ))

            if _INSPECT_ONLY_MODE:
                cout.info("Inspect-only mode: fetch elected courses only, skip any selection actions")
                cout.info("> Elected courses (%d)" % len(elected))
                for ix, ec in enumerate(elected):
                    cout.info("%02d. %s" % (ix + 1, ec))
                _log_loop_behavior(
                    "fetch_elected_only",
                    rotated_ip=rotated_ip,
                    live_ip=live_ip,
                    extra="elected_count=%d page_mode=%s" % (len(elected), mode),
                )
                continue

            ## check available courses

            cout.info("Get available courses")

            tasks = [] # [(ix, course)]
            for ix, c in enumerate(goals):
                if c in ignored:
                    continue
                elif c in elected:
                    cout.info("%s is elected, ignored" % c)
                    _ignore_course(c, "Elected")
                    for (mix, ) in np.argwhere( mutexes[ix,:] == 1 ):
                        mc = goals[mix]
                        if mc in ignored:
                            continue
                        cout.info("%s is simultaneously ignored by mutex rules" % mc)
                        _ignore_course(mc, "Mutex rules")
                else:
                    for c0 in plans: # c0 has detail
                        if c0 == c:
                            cout.info(
                                "Course observed: %s status=%s action=%s href=%s" % (
                                    c0.to_simplified(),
                                    c0.status,
                                    c0.action_text or "-",
                                    c0.href or "-",
                                )
                            )

                            has_action = c0.is_action_available()
                            is_available = has_action or c0.is_available()
                            if is_available:
                                delay = delays[ix]
                                if delay != NO_DELAY and c0.remaining_quota > delay:
                                    cout.info("%s hasn't reached the delay threshold %d, skip" % (c0, delay))
                                else:
                                    tasks.append((ix, c0))
                                    if has_action:
                                        cout.info("%s is ACTION-AVAILABLE now !" % c0)
                                    else:
                                        cout.info("%s is AVAILABLE now !" % c0)
                            break
                    else:
                        raise UserInputException("%s is not in your course plan, please check your config." % c)

            tasks = deque([ (ix, c) for ix, c in tasks if c not in ignored ]) # filter again and change to deque

            ## elect available courses

            if len(tasks) == 0:
                cout.info("No course available")
                continue

            elected = []  # cache elected courses dynamically from `get_ElectSupplement`

            while len(tasks) > 0:

                ix, course = tasks.popleft()

                is_mutex = False

                # dynamically filter course by mutex rules
                for (mix, ) in np.argwhere( mutexes[ix,:] == 1 ):
                    mc = goals[mix]
                    if mc in elected: # ignore course in advanced
                        is_mutex = True
                        cout.info("%s --x-- %s" % (course, mc))
                        cout.info("%s is ignored by mutex rules in advance" % course)
                        _ignore_course(course, "Mutex rules")
                        break

                if is_mutex:
                    continue

                cout.info("Try to elect %s" % course)

                ## validate captcha first

                while True:

                    cout.info("Fetch a captcha")
                    r = elective.get_DrawServlet()

                    captcha = recognizer.recognize(r.content)
                    cout.info("Recognition result: %s" % captcha.code)

                    r = elective.get_Validate(username, captcha.code)
                    try:
                        res = r.json()["valid"]  # 可能会返回一个错误网页
                    except Exception as e:
                        ferr.error(e)
                        raise OperationFailedError(msg="Unable to validate captcha")

                    if res == "2":
                        cout.info("Validation passed")
                        break
                    elif res == "0":
                        cout.info("Validation failed")
                        captcha.save(CAPTCHA_CACHE_DIR)
                        cout.info("Save %s to %s" % (captcha, CAPTCHA_CACHE_DIR))
                        cout.info("Try again")
                    else:
                        cout.warning("Unknown validation result: %s" % res)

                ## try to elect

                try:

                    r = elective.do_select_action(course.href)

                except ElectionRepeatedError as e:
                    ferr.error(e)
                    cout.warning("ElectionRepeatedError encountered")
                    _ignore_course(course, "Repeated")
                    _add_error(e)

                except TimeConflictError as e:
                    ferr.error(e)
                    cout.warning("TimeConflictError encountered")
                    _ignore_course(course, "Time conflict")
                    _add_error(e)

                except ExamTimeConflictError as e:
                    ferr.error(e)
                    cout.warning("ExamTimeConflictError encountered")
                    _ignore_course(course, "Exam time conflict")
                    _add_error(e)

                except ElectionPermissionError as e:
                    ferr.error(e)
                    cout.warning("ElectionPermissionError encountered")
                    # _ignore_course(course, "Permission required") 注释掉这行，试试
                    _add_error(e)
                    continue  # 继续循环，不退出

                except CreditsLimitedError as e:
                    ferr.error(e)
                    cout.warning("CreditsLimitedError encountered")
                    _ignore_course(course, "Credits limited")
                    _add_error(e)

                except MutexCourseError as e:
                    ferr.error(e)
                    cout.warning("MutexCourseError encountered")
                    _ignore_course(course, "Mutual exclusive")
                    _add_error(e)

                except MultiEnglishCourseError as e:
                    ferr.error(e)
                    cout.warning("MultiEnglishCourseError encountered")
                    _ignore_course(course, "Multi English course")
                    _add_error(e)

                except MultiPECourseError as e:
                    ferr.error(e)
                    cout.warning("MultiPECourseError encountered")
                    _ignore_course(course, "Multi PE course")
                    _add_error(e)

                except ElectionFailedError as e:
                    ferr.error(e)
                    cout.warning("ElectionFailedError encountered") # 具体原因不明，且不能马上重试
                    _add_error(e)

                except QuotaLimitedError as e:
                    ferr.error(e)
                    # 选课网可能会发回异常数据，本身名额 180/180 的课会发 180/0，这个时候选课会得到这个错误
                    if course.used_quota == 0:
                        cout.warning("Abnormal status of %s, a bug of 'elective.pku.edu.cn' found" % course)
                    else:
                        ferr.critical("Unexcepted behaviour") # 没有理由运行到这里
                        _add_error(e)

                except ElectionSuccess as e:
                    # 不从此处加入 ignored，而是在下回合根据教学网返回的实际选课结果来决定是否忽略
                    cout.info("%s is ELECTED !" % course)

                    # --------------------------------------------------------------------------
                    # Issue #25
                    # --------------------------------------------------------------------------
                    # 但是动态地更新 elected，如果同一回合内有多门课可以被选，并且根据 mutex rules，
                    # 低优先级的课和刚选上的高优先级课冲突，那么轮到低优先级的课提交选课请求的时候，
                    # 根据这个动态更新的 elected 它将会被提前地忽略（而不是留到下一循环回合的开始时才被忽略）
                    # --------------------------------------------------------------------------
                    r = e.response  # get response from error ... a bit ugly
                    tables = get_tables(r._tree)
                    # use clear() + extend() instead of op `=` to ensure `id(elected)` doesn't change
                    elected.clear()
                    elected.extend(get_courses(tables[1]))

                    # Send email notification
                    try:
                        import smtplib
                        from email.mime.text import MIMEText

                        sender = config.email_sender  # 发件人邮箱
                        receivers = config.email_receiver  # 收件人邮箱列表
                        smtp_server = config.email_smtp_server # smtp服务器
                        sender_password = config.email_sender_password # 密码

                        smtpObj = smtplib.SMTP_SSL(smtp_server, 465)  # SMTP服务器和端口
                        smtpObj.login(sender, sender_password)  # 登录
                        for receiver in receivers:
                            # 构造 HTML 格式的邮件正文
                            html_content = f"""
                            <html>
                              <head>
                                <style>
                                  body {{
                                    font-family: sans-serif;
                                  }}
                                  ul {{
                                    list-style: none;
                                    padding: 0;
                                  }}
                                  li {{
                                    margin-bottom: 0.5em;
                                  }}
                                  b {{
                                    font-weight: bold;
                                  }}
                                  .button {{
                                    background-color: #4CAF50; /* Green */
                                    border: none;
                                    color: white;
                                    padding: 15px 32px;
                                    text-align: center;
                                    text-decoration: none;
                                    display: inline-block;
                                    font-size: 16px;
                                    margin: 4px 2px;
                                    cursor: pointer;
                                  }}
                                </style>
                              </head>
                              <body>
                                <p>恭喜！您已成功选上课程:</p>
                                <ul>
                                  <li><b>课程题目:</b> {course.name}</li>
                                  <li><b>院系:</b> {course.school}</li>
                                  <li><b>班号:</b> {course.class_no}</li>
                                </ul>
                                <a href="https://elective.pku.edu.cn/" class="button">点击查看</a>
                              </body>
                            </html>
                            """

                            message = MIMEText(html_content, 'html', 'utf-8')
                            message['From'] = sender
                            message['To'] = receiver
                            message['Subject'] = '选课成功通知'
                            smtpObj.sendmail(sender, [receiver], message.as_string())
                            cout.info(f"邮件发送成功 to {receiver}")
                        smtpObj.quit() # 关闭连接
                    except Exception as e:
                        cout.error("邮件发送失败: %s" % e)

                except RuntimeError as e:
                    ferr.critical(e)
                    ferr.critical("RuntimeError with Course(name=%r, class_no=%d, school=%r, status=%s, href=%r)" % (
                                    course.name, course.class_no, course.school, course.status, course.href))
                    # use this private function of 'hook.py' to dump the response from `get_SupplyCancel` or `get_supplement`
                    file = _dump_request(page_r)
                    ferr.critical("Dump response from 'get_SupplyCancel / get_supplement' to %s" % file)
                    raise e

                except Exception as e:
                    raise e  # don't increase error count here

        except UserInputException as e:
            cout.error(e)  # 输出错误信息
            _add_error(e)  # 增加错误计数
            cout.warning("Course not found in current page, continue to next loop...")
            continue  # 继续循环而不是终止程序

        except (ServerError, StatusCodeError) as e:
            ferr.error(e)
            cout.warning("ServerError/StatusCodeError encountered")
            _add_error(e)

        except OperationFailedError as e:
            ferr.error(e)
            cout.warning("OperationFailedError encountered")
            _add_error(e)

        except UnexceptedHTMLFormat as e:
            ferr.error(e)
            cout.warning("UnexceptedHTMLFormat encountered")
            _add_error(e)

        except RequestException as e:
            ferr.error(e)
            cout.warning("RequestException encountered")
            _add_error(e)
            if not _INSPECT_ONLY_MODE and _is_emergency_network_error(e):
                _emergency_rotate_ip("Elective/IAAA TLS/network failure detected, rotate IP immediately")

        except IAAAException as e:
            ferr.error(e)
            cout.warning("IAAAException encountered")
            _add_error(e)

        except _ElectiveNeedsLogin as e:
            cout.info("client: %s needs Login" % elective.id)
            reloginPool.put_nowait(elective)
            elective = None
            noWait = True

        except _ElectiveExpired as e:
            cout.info("client: %s expired" % elective.id)
            reloginPool.put_nowait(elective)
            elective = None
            noWait = True

        except (SessionExpiredError, InvalidTokenError, NoAuthInfoError, SharedSessionError) as e:
            ferr.error(e)
            _add_error(e)
            cout.info("client: %s needs relogin" % elective.id)
            reloginPool.put_nowait(elective)
            elective = None
            noWait = True

        except CaughtCheatingError as e:
            ferr.critical(e) # critical error !
            _add_error(e)
            raise e

        except SystemException as e:
            ferr.error(e)
            cout.warning("SystemException encountered")
            _add_error(e)

        except TipsException as e:
            ferr.error(e)
            cout.warning("TipsException encountered")
            _add_error(e)

        except OperationTimeoutError as e:
            ferr.error(e)
            cout.warning("OperationTimeoutError encountered")
            _add_error(e)

        except json.JSONDecodeError as e:
            ferr.error(e)
            cout.warning("JSONDecodeError encountered")
            _add_error(e)

        except KeyboardInterrupt as e:
            raise e

        except Exception as e:
            ferr.exception(e)
            _add_error(e)
            raise e

        finally:

            if elective is not None: # change elective client
                electivePool.put_nowait(elective)
                elective = None

            # In inspect-only mode, if this round is just waiting for relogin,
            # skip rotate to avoid high-frequency churn without meaningful observation.
            if not (_INSPECT_ONLY_MODE and noWait):
                _rotate_ip_on_loop_end()

            if noWait:
                if _INSPECT_ONLY_MODE:
                    t = _get_refresh_interval()
                    cout.info("")
                    cout.info("======== END Loop %d ========" % environ.elective_loop)
                    cout.info("Inspect-only relogin wait, sleep %s s" % t)
                    cout.info("")
                    time.sleep(t)
                else:
                    cout.info("")
                    cout.info("======== END Loop %d ========" % environ.elective_loop)
                    cout.info("")
            else:
                t = _get_refresh_interval()
                cout.info("")
                cout.info("======== END Loop %d ========" % environ.elective_loop)
                cout.info("Main loop sleep %s s" % t)
                cout.info("")
                time.sleep(t)
