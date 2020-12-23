from config import *
from flask import Flask
from flask import abort, Response, request, send_from_directory
from flask_restful import reqparse
from werkzeug.utils import secure_filename
from env import *
import logging
from datetime import datetime
from botocore.client import Config
from botocore.exceptions import ClientError
from boto3 import client
from os.path import exists, join
from os import path, walk
from json import dumps
import pandas as pd
from io import BytesIO

app = Flask(__name__)
app.logger.addHandler(file_handler)
app.logger.addHandler(access_handler)
app.debug=False


def get_s3_client():
    s3_signature = {
        'v4': 's3v4',
        'v2': 's3'
    }
    return client('s3',
                     aws_access_key_id=AWS_ACCESS_KEY,
                     aws_secret_access_key=AWS_SECRET_KEY,
                     config=Config(signature_version=s3_signature['v4']),
                     region_name=AWS_DEFAULT_REGION
                     )

def create_presigned_post(bucket_name, object_name,
                          fields=None, conditions=None, expiration=3600):
    s3_client = get_s3_client()

    try:
        response = s3_client.generate_presigned_post(bucket_name,
                                                     object_name,
                                                     ExpiresIn=expiration)
    except ClientError as e:
        logging.error(e)
        return None
    return response

def add_timestamp(file):
    if '.' in file:
        fn=file.split('.')
        file='.'.join(fn[0:-1])+'_'+datetime.now().strftime('%Y%m%d%H%M%S')+'.'+fn[-1]
    else:
        file=str(file)+'_'+datetime.now().strftime('%Y%m%d%H%M%S')
    return file

@app.route('/data/upload-url',methods=['POST'])
def aws_upload_url():
    parser = reqparse.RequestParser()
    filename = parser.add_argument("filename")
    args = parser.parse_args()
    file=args["filename"]
    if file:
        file=add_timestamp(file)
        return create_presigned_post(EMISSION_BUCKET_NAME,str(file))
    else:
        abort(400, f'Bad request, validate the payload')

@app.route('/data/download_url',methods=['POST'])
def aws_file_download():
    s3_client = get_s3_client()
    parser = reqparse.RequestParser()
    filename = parser.add_argument("filename")
    bucket = parser.add_argument("bucket")
    args = parser.parse_args()
    bucket_name = get_bucket_name(args["bucket"])
    if args["filename"]:
        file_name=args["filename"]
    try:
        response = s3_client.generate_presigned_url('get_object',
                                                     Params={'Bucket':bucket_name,'Key':file_name},
                                                     ExpiresIn=86400)
    except ClientError as e:
        logging.error(e)
        return None
    return response

@app.route('/data/download_uri',methods=['POST'])
def aws_file_downloads():
    s3_client = get_s3_client()
    parser = reqparse.RequestParser()
    filename = parser.add_argument("filename", action='append')
    bucket = parser.add_argument("bucket")
    args = parser.parse_args()
    bucket_name = get_bucket_name(args["bucket"])
    if args["filename"]:
        file_name=args.get("filename")
    file_resp=dict()
    files=args["filename"]
    for file in files:
        try:
            response = s3_client.generate_presigned_url('get_object',
                                                         Params={'Bucket':bucket_name,'Key':file},
                                                         ExpiresIn=3600)
            file_resp[file]=response
        except ClientError as e:
            logging.error(e)
            return None
    return file_resp

def get_object(s3,bucket_name,file_name):
    return s3.get_object(Bucket=bucket_name, Key=file_name)['Body'].read()

def get_bucket_name(bucket):
    if bucket==INPUT_BUCKET_NAME or bucket==OUTPUT_BUCKET_NAME or bucket==EMISSION_BUCKET_NAME:
        return bucket
    else:
        abort(400, f'Bad request, not cqube bucket - validate the bucket name')

def valid_path(filename):
    full_path = join(BASE_DIR, filename)
    if not exists(full_path):
        return abort(404, f'Bad request, unable to find the file - validate the filename in payload')

@app.route('/data/list_s3_files',methods=['POST'])
def list_s3_files():
    parser = reqparse.RequestParser()
    bucket = parser.add_argument("bucket")
    args = parser.parse_args()
    bucket_name = get_bucket_name(args["bucket"])
    s3_client = get_s3_client()
    return s3_client.list_objects(Bucket=bucket_name)

@app.route('/data/download', methods=['POST'])
def index():
    s3 = get_s3_client()
    parser = reqparse.RequestParser()
    filename = parser.add_argument("filename")
    bucket = parser.add_argument("bucket")
    args = parser.parse_args()
    bucket_name = get_bucket_name(args["bucket"])
    if args["filename"]:
        return Response(
            get_object(s3, bucket_name, args["filename"]),
            mimetype='text/plain',
            headers={"Content-Disposition": "attachment;filename={}".format(args["filename"].split('/')[-1])}
        )
    else:
        abort(400, f'Bad request, validate the filename in payload')

@app.route('/data/list_s3_buckets',methods=['GET'])
def list_s3_buckets():
    return dumps({"input":INPUT_BUCKET_NAME,"output":OUTPUT_BUCKET_NAME,"emission":EMISSION_BUCKET_NAME})

@app.route('/data/list_log_files',methods=['GET'])
def files_list(file_path=BASE_DIR):
    file_list=list()
    for root, dirs, files in walk(file_path):
        file_list.append({"path": path.relpath(root, file_path), "directories": dirs, "files": files})
    return dumps(file_list)

@app.route('/data/log-download', methods=['POST'])
def log_download():
    parser = reqparse.RequestParser()
    filename = parser.add_argument("filename")
    args = parser.parse_args()
    if args["filename"]:
        valid_path(args["filename"])
        return send_from_directory(BASE_DIR,filename=args["filename"], as_attachment=True)
    else:
        abort(400, f'Bad request, filename not provided in payload')

def validate_weights(wdf):
    s3_client = get_s3_client()
    try:
        infra_file=s3_client.get_object(Bucket=OUTPUT_BUCKET_NAME,
                             Key="infrastructure_score/infrastructure_score.csv")
        df = pd.read_csv(BytesIO(infra_file['Body'].read()),sep='|')
        if wdf["score"].sum() == 100:
            if list(df.columns) == list(wdf.columns):
                if len(df[['infrastructure_name','infrastructure_category']].merge(wdf[['infrastructure_name','infrastructure_category']]).drop_duplicates())==len(df):
                    return True
                else:
                    abort(400, f'Bad data in file, please validate the data in infrastructure_name and infrastructure_category')
            else:
                abort(400, f'Bad file header, please check the file header')
        else:
            abort(400, f'Bad file, validate the score, infrastructure total score sum is not 100')
    except Exception as err:
        abort(400,err)

@app.route('/data/infra_weights',methods=['POST'])
def upload_file():
    uploaded_file = request.files['file']
    content_type = 'application/json'
    filename = secure_filename(uploaded_file.filename)
    if filename:
        s3_client = get_s3_client()
        csv_buffer = uploaded_file.read()
        wdf = pd.read_csv(BytesIO(csv_buffer),sep='|')
        validate_weights(wdf)
        resp = s3_client.put_object(Body=csv_buffer,
                          Bucket=EMISSION_BUCKET_NAME,
                          Key="infrastructure_score/infrastructure_score.csv",
                          ContentType=content_type)
        return resp

@app.route('/data/infra_score', methods=['GET'])
def get_infra_score():
    s3_client = get_s3_client()
    key="infrastructure_score/infrastructure_score.csv"
    try:
        return Response(
            get_object(s3_client, OUTPUT_BUCKET_NAME, key ),
            mimetype='text/plain',
            headers={"Content-Disposition": "attachment;filename={}".format(key.split('/')[-1])}
        )
    except Exception as err:
        abort(400, f'Bad request, validate the payload')

@app.route('/data/test', methods=['GET'])
def get_diksha():
    return '''{
    "id": "org.ekstep.analytics.telemetry",
    "ver": "1.0",
    "ts": "2020-11-25T10:04:08.108+00:00",
    "params": {
        "resmsgid": "<resmsgid>",
        "status": "successful",
        "client_key": null
    },
    "responseCode": "OK",
    "result": {
        "files": [
            "<URL>",
            "<URL>",
            "<URL>",
            "<URL>",
            "<URL>",
            "<URL>",
            "<URL>",
            "<URL>"
        ],
        "periodWiseFiles": {
            "2020-11-23": [
                "https://cqube-emission.s3.amazonaws.com/diksha_data_summary_less_api.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA2YWRVRZFDHGEDYVM%2F20201223%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20201223T141534Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=19d67e3404de5fce8c4950804b3bb13fab21f5a99b4872a2a46cd7e39014fb91"
            ],
            "2020-11-17": [
                "https://cqube-emission.s3.amazonaws.com/diksha_data_summary_less_api.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA2YWRVRZFDHGEDYVM%2F20201223%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20201223T141559Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=6aa14d3b53ee5417587131ecdfc6c0a121e71cd82794f6b88e56c3e2322cd0fe"
            ],
            "2020-11-18": [
                "https://cqube-emission.s3.amazonaws.com/diksha_data_summary_less_api.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA2YWRVRZFDHGEDYVM%2F20201223%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20201223T141709Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=2fe3a413cb3e0d08a68d075b3a0cd9023fcaa960d65f81b08e953d02495e9b23"
            ],
            "2020-11-19": [
                "https://cqube-emission.s3.amazonaws.com/diksha_data_summary_less_api.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA2YWRVRZFDHGEDYVM%2F20201223%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20201223T142326Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=a706f56580f03249920c8065d029a35c17bdeee9a94f48063a42ac8cb27218b2"
            ],
            "2020-11-20": [
                "https://cqube-emission.s3.amazonaws.com/diksha_data_summary_less_api.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA2YWRVRZFDHGEDYVM%2F20201223%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20201223T142409Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=822bfc89361eedd2ba0821308bd4e77e94947d012394192657badce69fd0548f"
            ],
            "2020-11-21": [
                "https://cqube-emission.s3.amazonaws.com/diksha_data_summary_less_api.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA2YWRVRZFDHGEDYVM%2F20201223%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20201223T142429Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=07d116cca8b6d8edc1f2ed30c78ea2fa9a98631974bc68de8719ddeef0e00c85"
            ],
            "2020-11-22": [
                "https://cqube-emission.s3.amazonaws.com/diksha_data_summary_less_api.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=AKIA2YWRVRZFDHGEDYVM%2F20201223%2Fap-south-1%2Fs3%2Faws4_request&X-Amz-Date=20201223T143008Z&X-Amz-Expires=86400&X-Amz-SignedHeaders=host&X-Amz-Signature=4b95501eafab3e109a09598de42266910d88cb447eceb7929e550b23b4a6c91d"
            ]
        },
        "expiresAt": 1606300498990
    }
}'''
