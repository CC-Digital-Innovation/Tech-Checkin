import os
import secrets
import sys
from datetime import date, datetime, timezone
from pathlib import PurePath

import dotenv
from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import APIKeyHeader
from geopy.geocoders import GeoNames
from loguru import logger
from pydantic import BaseModel

import check_in
from alt_smartsheet import SmartsheetController
from sms import TextbeltController, TwilioController

#load secrets from environemnt variables defined in deployement
dotenv.load_dotenv(PurePath(__file__).with_name('.env'))

#assign environment variables to globals
API_KEY = os.getenv('API_KEY')

# logging config
LOGGING_LEVEL = os.getenv('LOGGING_LEVEL', 'INFO')
logger.configure(handlers=[{'sink': sys.stderr, 'level': LOGGING_LEVEL}])

# initialize smartsheet
SMARTSHEET_REPORT_ID = os.environ['SMARTSHEET_REPORT_ID']
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL')  # Optional. Used to ping in smartsheets.
smartsheet_controller = SmartsheetController()
report = smartsheet_controller.get_report(SMARTSHEET_REPORT_ID)  # test access

# Initialize N8N global environment variables.
N8N_BASE_URL = os.getenv('N8N_BASE_URL')
N8N_WORKFLOW_ID = os.getenv('N8N_WORKFLOW_ID')

# initalize geolocator
GEONAMES_USER = os.environ['GEONAMES_USER']
geolocator = GeoNames(username=GEONAMES_USER)

ADMIN_PHONE_NUMBER = os.getenv('ADMIN_PHONE_NUMBER')
SMS_TOOL=os.getenv('SMS_TOOL', 'textbelt').lower()
if SMS_TOOL == 'textbelt':
    TEXTBELT_KEY = os.environ['TEXTBELT_KEY']
    TEXTBELT_SENDER = os.environ['TEXTBELT_SENDER']
    sms_controller = TextbeltController(TEXTBELT_KEY, TEXTBELT_SENDER, ADMIN_PHONE_NUMBER)
elif SMS_TOOL == 'twilio':
    TWILIO_API_SID = os.environ['TWILIO_API_SID']
    TWILIO_API_KEY = os.environ["TWILIO_API_KEY"]
    TWILIO_FROM = os.environ['TWILIO_FROM']
    sms_controller = TwilioController(TWILIO_API_SID, TWILIO_API_KEY, TWILIO_FROM, ADMIN_PHONE_NUMBER)
else:
    raise ValueError(f'SMS tool {SMS_TOOL} is not supported.')

# setup scheduler
CRONJOB_24_CHECKS = CronTrigger.from_crontab(os.environ['CRONJOB_24_CHECKS'])
CRONJOB_1_CHECKS = CronTrigger.from_crontab(os.environ['CRONJOB_1_CHECKS'])
scheduler = BackgroundScheduler()
# schedule 1 hour calls inbetween deployment time and next scheduled 1 hour pre-calls
check_in.schedule_1_hour_checks(scheduler, report, geolocator, sms_controller, smartsheet_controller, CRONJOB_1_CHECKS.get_next_fire_time(None, datetime.now(timezone.utc)))
# add 24 and 1 hour check jobs using crontab expression
scheduler.add_job(check_in.send_24_hour_checks, CRONJOB_24_CHECKS, args=[report, geolocator, f'{N8N_BASE_URL}/{N8N_WORKFLOW_ID}', sms_controller])
scheduler.add_job(check_in.schedule_1_hour_checks, CRONJOB_1_CHECKS, args=[scheduler, report, geolocator, sms_controller, smartsheet_controller])
scheduler.start()

#init app - rename with desired app name
checkin = FastAPI()

#init key for auth
api_key = APIKeyHeader(name='API-Key')

#auth key
def authorize(key: str = Depends(api_key)):
    if not secrets.compare_digest(key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid token')


class Form(BaseModel):
    tech_name: str
    date: date
    time: str
    location: str
    site_id: str
    work_market_num: str
    comment: str | None = None


@checkin.post('/forms/submit', dependencies=[Depends(authorize)], tags=['Forms'])
def submit_form(form: Form):
    logger.debug(form)
    logger.info(f'Form submitted for {form.work_market_num}')
    report = smartsheet_controller.get_report(SMARTSHEET_REPORT_ID)  # get sheet updates
    #take above parameters and either correct row in smartsheet and/or @ person in resposible collumn for correction to be made
    try:
        row = next(row for row in report.get_rows() if report.get_work_market_num_id(row) == form.work_market_num)
    except StopIteration:
        logger.error(f'Failed to handle form submission. Cannot find row with Work Market # of {form.work_market_num}.')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Canont find row with Work Market # of {form.work_market_num}.')
    if report.get_24_hour_checkbox(row):
        # already complete, ignore request
        msg = 'Form is already complete. Ignoring any further requests.'
        logger.warning(msg)
        return msg

    # compare fields for changes
    tech_details = report.get_tech_details(row)
    comments = []  # will take advantage of join() function
    if tech_details.tech_name != form.tech_name:
        comments.append(f"Tech needs to be changed to {form.tech_name}.")
    if tech_details.site_id != form.site_id:
        comments.append(f"Site ID needs to be changed to {form.site_id}.")
    parsed_time = datetime.strptime(form.time, check_in.TIME_FORM_FORMAT).time()
    if tech_details.appt_datetime.time() != parsed_time:
        comments.append(f"Appointment time needs to be changed to {parsed_time.strftime(check_in.TIME_FORM_FORMAT)}.")
    if tech_details.appt_datetime.date() != form.date:
        comments.append(f"Appointment date needs to be changed to {form.date}.")
    if tech_details.address != form.location:
        comments.append(f"Address needs to be changed to {form.location}.")

    # no comments means no changes were found, mark 24 hr check complete
    if not comments:
        report.set_24_hour_checkbox(row, True)
        logger.info(f'Appointment {form.work_market_num} is correct. Updating 24 HR Pre-call checkbox...')
        smartsheet_controller.update_report_rows(report)

    # regardless of correctness, accept addtional comments
    if form.comment:
        comments.append(f"Additional comment from tech: {form.comment}")

    # combine comments and add to row
    if comments:
        if ADMIN_EMAIL:
            comments.append(f'@{ADMIN_EMAIL}')  # ping admin email
        comments = '\n'.join(comments)
        smartsheet_controller.create_discussion_on_row(row.sheet_id, row.id, comments)
    msg = f'24 hour pre-call complete for {form.work_market_num}'
    logger.info(msg)
    return msg


class JobView(BaseModel):
    id: str
    name: str
    next_run_time: datetime

    @classmethod
    def from_job(cls, job: Job):
        return cls(id=job.id, name=job.name, next_run_time=job.next_run_time)

@checkin.get('/jobs', dependencies=[Depends(authorize)], tags=['Jobs'])
def list_jobs() -> list[JobView]:
    return [JobView.from_job(job) for job in scheduler.get_jobs()]

@checkin.get('/jobs/{id}', dependencies=[Depends(authorize)], tags=['Jobs'])
def get_job(id: str) -> JobView:
    return JobView.from_job(scheduler.get_job(id))
