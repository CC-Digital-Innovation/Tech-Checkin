import urllib.parse
from datetime import date, datetime, timedelta

import phonenumbers
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from geopy import GeoNames
from loguru import logger
from phonenumbers import PhoneNumberFormat

from alt_smartsheet import AllTrackerSheet, TechDetails
from sms import SMSBaseController


def build_form(url: str, tech_details: TechDetails):
    params = {
        'Tech Name': tech_details.tech_name,
        'Time': tech_details.appt_datetime,
        'Location': tech_details.address,
        'Site ID': tech_details.site_id,
        "Work Number - Please don't change" : tech_details.work_market_num
    }
    return f'{url}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}'

def send_24_hour_checks(sheet: AllTrackerSheet, geolocator: GeoNames, form_url: str, sms_controller: SMSBaseController):
    logger.info('Scheduling 24 hour checks...')
    # filter rows by tomorrow's date and unfinished checks
    tomorrow = date.today() + timedelta(days=1)
    for row in sheet.get_rows():
        if sheet.get_24_hour_checkbox(row):
            continue  # already checked
        try:
            appt_date = sheet.get_appt_date(row)
        except ValueError as e:
            error_msg = f'Error parsing date for row #{row.row_number}. Error: "{e}"'
            if sms_controller.admin_num:
                sms_controller.send_text(sms_controller.admin_num, error_msg)
            logger.error(error_msg)
            continue
        if tomorrow == appt_date:
            try:
                tech_details = sheet.get_tech_details(row, geolocator)
            except ValueError as e:
                error_msg = f'Could not schedule 24 hour pre-text while parsing row #{row.row_number}. Error: "{e}"'
                if sms_controller.admin_num:
                    sms_controller.send_text(sms_controller.admin_num, error_msg)
                logger.error(error_msg)
                continue
            url = build_form(form_url, tech_details)
            send_to = phonenumbers.format_number(tech_details.tech_contact, PhoneNumberFormat.E164)
            sms_controller.send_text(send_to,
                                     f'Please confirm the details of your appointment tomorrow: {url}')

def get_1_hour_checks(sheet: AllTrackerSheet, geolocator: GeoNames, sms_controller: SMSBaseController) -> list[tuple[datetime, TechDetails]]:
    # filter rows by today's date and unfinished checks
    now = datetime.now(pytz.utc)
    tomorrow = now + timedelta(days=1)
    rows_to_check = []
    for row in sheet.get_rows():
        if sheet.get_1_hour_checkbox(row):
            continue  # already checked
        try:
            tech_details = sheet.get_tech_details(row, geolocator)
        except ValueError as e:
            error_msg = f'Could not schedule 1 hour pre-text while parsing row #{row.row_number}. Error: "{e}"'
            if sms_controller.admin_num:
                sms_controller.send_text(sms_controller.admin_num, error_msg)
            continue
        if now < tech_details.appt_datetime < tomorrow:
            rows_to_check.append(((tech_details.appt_datetime - timedelta(hours=1)), tech_details))
    return rows_to_check

def send_1_hour_check(tech_details: TechDetails, sms_controller: SMSBaseController):
    send_to = phonenumbers.format_number(tech_details.tech_contact, PhoneNumberFormat.E164)
    sms_controller.send_text(send_to,
                             f'Reminder that your appointment (ID {tech_details.site_id}) is in one hour !')

def schedule_1_hour_checks(scheduler: BackgroundScheduler, sheet: AllTrackerSheet, geolocator: GeoNames, sms_controller: SMSBaseController):
    logger.info('Scheduling 1 hour checks...')
    # get 1 hour checks for the day
    checks = get_1_hour_checks(sheet, geolocator, sms_controller)
    for appt_datetime, tech_details in checks:
        scheduler.add_job(send_1_hour_check, trigger='date', run_date=appt_datetime, args=[tech_details, sms_controller])
