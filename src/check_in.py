import urllib.parse
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from geopy import GeoNames
from loguru import logger

from alt_smartsheet import AllTrackerSheet, TechDetails
from alt_twilio import send_text


def build_form(url: str, tech_details: TechDetails):
    params = {
        'Tech Name': tech_details.tech_name,
        'Time': tech_details.appt_datetime,
        'Location': tech_details.address,
        'Site ID': tech_details.site_id
    }
    return f'{url}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}'

def send_24_hour_checks(sheet: AllTrackerSheet, geolocator: GeoNames, form_url: str):
    logger.info('Scheduling 24 hour checks...')
    # filter rows by tomorrow's date and unfinished checks
    now = datetime.now(pytz.utc)
    tomorrow = now + timedelta(days=1)
    two_days_later = now + timedelta(days=2)
    for row in sheet.get_rows():
        if sheet.get_24_hour_checkbox(row):
            continue  # already checked
        tech_details = sheet.get_tech_details(row, geolocator)
        if tomorrow > tech_details.appt_datetime or two_days_later < tech_details.appt_datetime:
            continue  # outside tomorrow time range
        logger.debug(f'Tech Details: {tech_details}')
        url = build_form(form_url, tech_details)
        logger.debug(f'URL: {url}')
        send_text(tech_details.tech_contact, f'Please confirm the details of your appointment tomorrow: {url}')

def get_1_hour_checks(sheet: AllTrackerSheet, geolocator: GeoNames) -> list[tuple[datetime, TechDetails]]:
    # filter rows by today's date and unfinished checks
    now = datetime.now(pytz.utc)
    tomorrow = now + timedelta(days=1)
    rows_to_check = []
    for row in sheet.get_rows():
        if sheet.get_1_hour_checkbox(row):
            continue  # already checked
        tech_details = sheet.get_tech_details(row, geolocator)
        if now > tech_details.appt_datetime or tomorrow < tech_details.appt_datetime:
            continue  # outside of today time range
        # rows_to_check.append(((tech_details.appt_datetime - timedelta(hours=1)), tech_details))
        logger.debug('Testing scheduler by changing to next minute')
        rows_to_check.append((datetime.now(pytz.utc) + timedelta(minutes=1), tech_details))
    return rows_to_check

def send_1_hour_check(tech_details: TechDetails):
    logger.debug(f'Tech Details: {tech_details}')
    send_text(tech_details.tech_contact, 'Reminder that your appointment is in one hour. Please confirm the following details again...')

def schedule_1_hour_checks(scheduler: BackgroundScheduler, sheet: AllTrackerSheet, geolocator: GeoNames):
    logger.info('Scheduling 1 hour checks...')
    # get 1 hour checks for the day
    checks = get_1_hour_checks(sheet, geolocator)
    for appt_datetime, tech_details in checks:
        scheduler.add_job(send_1_hour_check, trigger='date', run_date=appt_datetime, args=[tech_details])
