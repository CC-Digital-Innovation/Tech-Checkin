import os
import secrets
import sys
import urllib.parse
from pathlib import PurePath

import dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import APIKeyHeader
from geopy.geocoders import GeoNames
from loguru import logger

import check_in
from alt_smartsheet import SmartsheetController

#load secrets from environemnt variables defined in deployement
dotenv.load_dotenv(PurePath(__file__).with_name('.env'))

#assign environment variables to globals
API_KEY = os.getenv('SECRET_NAME_FROM_deployment.yml')

# logging config
LOGGING_LEVEL = os.getenv('LOGGING_LEVEL', 'INFO')
logger.configure(handlers=[{'sink': sys.stderr, 'level': LOGGING_LEVEL}])

# initialize smartsheet
SMARTSHEET_SHEET_ID = os.environ['SMARTSHEET_SHEET_ID']
smartsheet_controller = SmartsheetController()
sheet = smartsheet_controller.get_sheet(SMARTSHEET_SHEET_ID)

# Initialize N8N global environment variables.
N8N_BASE_URL = os.getenv('N8N_BASE_URL')
N8N_WORKFLOW_ID = os.getenv('N8N_WORKFLOW_ID')

# initalize geolocator
GEONAMES_USER = os.environ['GEONAMES_USER']
geolocator = GeoNames(username=GEONAMES_USER)

# setup scheduler
CRONJOB_CHECKS = CronTrigger.from_crontab(os.environ['CRONJOB_CHECKS'])
scheduler = BackgroundScheduler()
# add 24 hour check jobs using crontab expression
scheduler.add_job(check_in.send_24_hour_checks, CRONJOB_CHECKS, args=[sheet, geolocator, f'{N8N_BASE_URL}/{N8N_WORKFLOW_ID}'])
scheduler.add_job(check_in.schedule_1_hour_checks, CRONJOB_CHECKS, args=[scheduler, sheet, geolocator])
scheduler.start()

#init app - rename with desired app name
checkin = FastAPI()

#init key for auth
api_key = APIKeyHeader(name='API-Key-Name')

#auth key
def authorize(key: str = Depends(api_key)):
    if not secrets.compare_digest(key, API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid token')


#sample get
@checkin.post('/formsubmit', dependencies=[Depends(authorize)])
def form(Tech_Name: str,
        Time: str,
        Location: str,
        Site_ID: str,
        Correct: str,
        CC_Email: str,
        Officetrak: str,
        Other_Correction: str):
    #take above parameters and either correct row in smartsheet and/or @ person in resposible collumn for correction to be made
    pass

#sample post
@checkin.post('/24hrtext', dependencies=[Depends(authorize)])
def dailytext(techname: str,
              location: str,
              time: str,
              siteid: str):
    techname_url = urllib.parse.quote_plus(techname)
    location_url = urllib.parse.quote_plus(location)
    time_url = urllib.parse.quote_plus(time)
    siteid_url = urllib.parse.quote_plus(siteid)
    base_url = "TBD"
    form = "secret"

    form_url = f"http://{base_url}/form/{form}?Tech%20Name={techname_url}&Time={time_url}&Location={location_url}&Site%20ID={siteid_url}"

    #then Twilio to text above url
    
