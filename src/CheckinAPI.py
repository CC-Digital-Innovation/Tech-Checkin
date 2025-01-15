from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from fastapi.security import APIKeyHeader
from pathlib import PurePath
import urllib.parse
import secrets
import dotenv
import os

#load secrets from environemnt variables defined in deployement
dotenv.load_dotenv(PurePath(__file__).with_name('.env'))

#assign environment variables to globals
API_KEY = os.getenv('SECRET_NAME_FROM_deployment.yml')

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
    



