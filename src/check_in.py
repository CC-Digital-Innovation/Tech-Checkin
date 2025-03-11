import urllib.parse
from datetime import date, datetime, timedelta
from typing import NamedTuple

import phonenumbers
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from geopy import GeoNames
from loguru import logger
from phonenumbers import PhoneNumberFormat
from smartsheet.sheets import Row

from alt_smartsheet import AllTrackerReport, SmartsheetController, TechDetails
from sms import SMSBaseController, TextbeltController

DATETIME_SMS_FORMAT = '%a %b, %d %Y @ %I:%M%p'
TIME_FORM_FORMAT = '%H%M'

def build_form(url: str, tech_details: TechDetails, sms_controller: SMSBaseController | None = None):
    params = {
        'Tech Name': tech_details.tech_name,
        'Date': tech_details.appt_datetime.date().isoformat(),
        'Time': tech_details.appt_datetime.time().strftime(TIME_FORM_FORMAT),
        'Location': tech_details.address,
        'Site ID': tech_details.site_id,
        'Work Order': tech_details.work_order_num,
        "Work Number - Please don't change" : tech_details.work_market_num
    }
    if isinstance(sms_controller, TextbeltController):
        url = f'{url}?{urllib.parse.urlencode(params)}'
        # specific issue where Textbelt decodes #, breaking the url sent
        if '#' in params['Site ID']:
            url = url.replace('%23', '%2523')  # let textbelt decode only code %25 (% symbol), leaving code %23 (# symbol)
    else:
        url = f'{url}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}'
    logger.debug(url)
    return url

def send_24_hour_checks(report: AllTrackerReport, geolocator: GeoNames, form_url: str, sms_controller: SMSBaseController):
    logger.info('Scheduling 24 hour checks...')
    # filter rows by tomorrow's date and unfinished checks
    tomorrow = date.today() + timedelta(days=1)
    for row in report.get_rows():
        if report.get_24_hour_checkbox(row):
            continue  # already checked
        try:
            appt_date = report.get_appt_date(row)
        except (ValueError, TypeError) as e:
            error_msg = f'Error parsing date for row #{row.row_number}: "{e}"'
            if sms_controller.admin_num:
                sms_controller.send_text(sms_controller.admin_num, error_msg)
            logger.error(error_msg)
            continue
        if tomorrow == appt_date:
            try:
                tech_details = report.get_tech_details(row, geolocator)
            except ValueError as e:
                error_msg = f'Could not schedule 24 hour pre-text while parsing row #{row.row_number}: "{e}"'
                if sms_controller.admin_num:
                    sms_controller.send_text(sms_controller.admin_num, error_msg)
                logger.error(error_msg)
                continue
            url = build_form(form_url, tech_details, sms_controller)
            send_to = phonenumbers.format_number(tech_details.tech_contact, PhoneNumberFormat.E164)
            logger.info(f'Sending 24 hour pre-call for {tech_details.work_market_num} to {send_to}.')
            try:
                resp = sms_controller.send_text(send_to,
                                                'Please confirm the details of your appointment tomorrow at '
                                                f'{tech_details.appt_datetime.strftime(DATETIME_SMS_FORMAT)}: {url}')
            except RuntimeError as e:
                logger.error(f'Could not send 24 hour pre-text for row #{row.row_number}: "{e}"')
            logger.debug(resp)


def send_24_hour_check(id: str, report: AllTrackerReport, geolocator: GeoNames, form_url: str, sms_controller: SMSBaseController):
    try:
        row = next(row for row in report.get_rows() if report.get_work_market_num_id(row) == id)
    except StopIteration:
        raise ValueError(f'Cannot find record with work market #{id}.')
    if report.get_24_hour_checkbox(row):
        raise ValueError(f'24HR Pre-call is already checked.')
    tech_details = report.get_tech_details(row, geolocator)
    url = build_form(form_url, tech_details, sms_controller)
    send_to = phonenumbers.format_number(tech_details.tech_contact, PhoneNumberFormat.E164)
    logger.info(f'Sending 24 hour pre-call for {tech_details.work_market_num} to {send_to}.')
    resp = sms_controller.send_text(send_to,
                                    'Please confirm the details of your appointment at '
                                    f'{tech_details.appt_datetime.strftime(DATETIME_SMS_FORMAT)}: {url}')
    logger.debug(resp)
    return {
        'to': send_to,
        'tech_name': tech_details.tech_name,
        'work_market_num': tech_details.work_market_num,
        'site_id': tech_details.site_id,
        'link': url
    }


class OneHRPrecall(NamedTuple):
    sched_time: datetime
    tech_details: TechDetails
    row: Row


def get_1_hour_checks(report: AllTrackerReport, geolocator: GeoNames, sms_controller: SMSBaseController, until: datetime | None = None) -> list[tuple[datetime, TechDetails]]:
    # filter rows by today's date and unfinished checks
    now = datetime.now(pytz.utc)
    if until is None:
        until = now + timedelta(days=1)
    rows_to_check = []
    for row in report.get_rows():
        if report.get_1_hour_checkbox(row):
            continue  # already checked
        try:
            tech_details = report.get_tech_details(row, geolocator)
        except ValueError as e:
            error_msg = f'Could not schedule 1 hour pre-text while parsing row #{row.row_number}. Error: "{e}"'
            if sms_controller.admin_num:
                sms_controller.send_text(sms_controller.admin_num, error_msg)
            logger.error(error_msg)
            continue
        if now < tech_details.appt_datetime < until:
            rows_to_check.append(OneHRPrecall(sched_time=tech_details.appt_datetime.tzinfo.normalize(tech_details.appt_datetime - timedelta(hours=1)),
                                            tech_details=tech_details,
                                            row=row))
    return rows_to_check

def send_1_hour_check(tech_details: TechDetails,
                      sms_controller: SMSBaseController,
                      row: Row,
                      report: AllTrackerReport,
                      smartsheet_controller: SmartsheetController):
    send_to = phonenumbers.format_number(tech_details.tech_contact, PhoneNumberFormat.E164)
    logger.info(f'Sending 1 hour pre-call to {send_to}.')
    try:
        resp = sms_controller.send_text(send_to,
                                        f'Reminder that your appointment (ID {tech_details.site_id}) at {tech_details.address} is in one hour!')
    except RuntimeError as e:
        logger.error(f'Could not send 1 hour pre-text for row #{row.row_number}: "{e}"')
        return
    logger.debug(resp)
    report.set_1_hour_checkbox(row, True)
    smartsheet_controller.update_report_rows(report)
    return {
        'to': send_to,
        'tech_name': tech_details.tech_name,
        'work_market_num': tech_details.work_market_num,
        'site_id': tech_details.site_id
    }

def schedule_1_hour_checks(scheduler: BackgroundScheduler,
                           report: AllTrackerReport,
                           geolocator: GeoNames,
                           sms_controller: SMSBaseController,
                           smartsheet_controller: SmartsheetController,
                           until: datetime | None = None):
    logger.info('Scheduling 1 hour checks...')
    # get 1 hour checks for the day
    checks = get_1_hour_checks(report, geolocator, sms_controller, until)
    for sched_time, tech_details, row in checks:
        logger.info(f'Scheduling 1 hour pre-call for {tech_details.work_market_num} @ {sched_time}.')
        scheduler.add_job(send_1_hour_check, trigger='date', run_date=sched_time, args=[tech_details, sms_controller, row, report, smartsheet_controller])

def schedule_1_hour_check(scheduler: BackgroundScheduler,
                          id: str,
                          report: AllTrackerReport,
                          geolocator: GeoNames,
                          sms_controller: SMSBaseController,
                          smartsheet_controller: SmartsheetController):
    row = next(row for row in report.get_rows() if report.get_work_market_num_id(row) == id)
    if report.get_24_hour_checkbox(row):
        raise ValueError(f'1HR Pre-call is already checked.')
    tech_details = report.get_tech_details(row, geolocator)
    sched_time = tech_details.appt_datetime.tzinfo.normalize(tech_details.appt_datetime - timedelta(hours=1))
    if sched_time < datetime.now(pytz.utc):
        raise ValueError(f'Cannot schedule in the past: {sched_time.isoformat()}')
    return scheduler.add_job(send_1_hour_check, trigger='date', run_date=sched_time, args=[tech_details, sms_controller, row, report, smartsheet_controller])
