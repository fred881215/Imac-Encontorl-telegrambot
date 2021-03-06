import telegram
from telegram.ext import Updater, Dispatcher, MessageHandler, Filters, CallbackQueryHandler, ConversationHandler, CommandHandler
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from pymongo import MongoClient
from imgurpython import ImgurClient
import pyimgur
import configparser
import datetime
import time
import cv2
import os
import schedule
import ossaudiodev
import _thread
import socket

config = configparser.ConfigParser()
config.read('config.ini')

bot = telegram.Bot(token=(config['TELEGRAM']['ACCESS_TOKEN']))

# mongo atlas URL
myMongoClient = MongoClient(config['MONGODB']['URL'])
myMongoDb = myMongoClient["smart-data-center"]

# 攝影功能
dbCameraControl = myMongoDb['cameraControl']
dbCameraCreate = myMongoDb['cameraCreate']

# imgur 圖床設置
client_id = 'b0ab73e0ddc8fc4'
client_secret = 'ed9354c61ef5dd4f14639e86d533f58d7ba3d7e9'
client = ImgurClient(client_id, client_secret)

# 錄影請求等候清單
schedule_camera = []

def main():
    # 客戶端新增攝像機請求
    def func_CameraCreate():
        print("=====CameraCreate=====")
        create_page = dbCameraCreate.find_one()
        if create_page["status"] == "1":
            # 使用 socket 套件進行 IP + Port 連通測試
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((create_page["ip"], int(create_page["port"])))
            sock.close()
            if result == 0:
                respText = "攝像機新增完成～"
                # 新增攝像機資料, 編號自動遞增
                count_list = len([i for i in dbCameraControl.find()])
                dbCameraControl.update_one({"device_number":str(count_list+1)}, {"$set":{"status":"0", "device_name":create_page["name"], "device_location":create_page["location"], "device_ip":create_page["ip"], "device_port":create_page["port"], "pin_code":create_page["pin_code"], "video_second":"", "chat_id":"", "connection":"0"}}, upsert=True)
            else:
                respText = "該位址無法連通, 請修正後重新嘗試～"
            print(respText)
            # 測試結果回傳給使用者
            bot.send_message(chat_id=create_page["chat_id"], text=respText, parse_mode="Markdown")
            # 使用者請求清空
            dbCameraCreate.update_one({"feature":"datapost"}, {"$set":{"status":"0", "name":"", "location":"", "ip":"", "port":"", "pin_code":"", "chat_id":""}}, upsert=True)
    # 客戶端使用攝像機請求
    def func_CameraControl():
        print("=====CameraControl=====")
        all_camera = dbCameraControl.find()
        global schedule
        for camera in all_camera:
            if camera["status"] == "1" or camera["status"] == "2":
                print("-----" + camera["device_name"] + "-----")
                # 攝像機連線檢查
                # 使用 socket 套件進行 IP + Port 連通測試
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = sock.connect_ex((camera["device_ip"], int(camera["device_port"])))
                sock.close()
                if result == 0:
                    url = 'rtsp://admin:' + camera["pin_code"] + '@' + camera["device_ip"] + ':' + camera["device_port"] + '/live/profile.0'
                    # 拍照功能
                    if camera["status"] == "1":
                        # 導入攝像機
                        cap = cv2.VideoCapture(url)
                        # 圖片名稱為當前時間 + .jpg(副檔名)
                        nowtime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        filename = str(nowtime) + ".jpg"
                        ret, frame = cap.read()
                        # 圖片暫存
                        cv2.imwrite(filename, frame)
                        # 攝像機記憶體空間釋放
                        cap.release()
                        # 圖片上傳至 imgur 後刪除本地存檔
                        im = pyimgur.Imgur(client_id)
                        uploaded_image = im.upload_image(filename, title="ImacPicture_" + str(nowtime))
                        os.remove(filename)
                        # 圖片網址回傳給使用者
                        respText = uploaded_image.link
                        bot.send_message(chat_id=camera["chat_id"], text=respText, parse_mode="Markdown")
                        # 使用者請求清空
                        dbCameraControl.update_one({"device_number":camera["device_number"]}, {"$set":{"status":"0", "video_second":"", "chat_id":"", "connection":"0"}}, upsert=True)
                    # 攝影功能
                    elif camera["status"] == "2":
                        def video_job(chat_id, device_number, video_second, url):
                            # 導入攝像機
                            cap = cv2.VideoCapture(url)
                            # 使用者請求清空
                            dbCameraControl.update_one({"device_number":device_number}, {"$set":{"status":"0", "video_second":"", "chat_id":"", "connection":"0"}}, upsert=True)
                            # 使用 mp4v 編碼
                            recordForucc = cv2.VideoWriter_fourcc(*"XVID")
                            # 取得攝影機 fps 設定值
                            recordFPS = int(cap.get(cv2.CAP_PROP_FPS))
                            # 取得影像的解析度大小
                            recordWidth = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                            recordHeight = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            # 影像檔命名為當前時間
                            nowtime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            filename = str(nowtime) + ".avi"
                            # 建立 VideoWriter 物件，輸出影片至 $(datetime).avi
                            out = cv2.VideoWriter(filename, recordForucc, recordFPS/2, (recordWidth, recordHeight))
                            # 時間換算, 對比約為 1:15
                            cnt = 1
                            if video_second == "15":
                                timer = 225
                            elif video_second == "30":
                                timer = 450
                            elif video_second == "60":
                                timer = 900
                            # 迴圈錄影
                            while cnt < timer:
                                ret, frame = cap.read()
                                out.write(frame)
                                cnt += 1
                            # 回傳錄像給使用者
                            bot.send_video(chat_id=chat_id, video=open(filename, 'rb'), supports_streaming=True)
                            # 刪除等候隊列和影像存檔
                            if device_number in schedule_camera:
                                print("delete! number:" + device_number)
                                schedule_camera.remove(device_number)
                            os.remove(filename)
                            # 攝像機記憶體空間釋放
                            cap.release()
                            out.release()
                        # 檢查攝像機是否在行程中
                        if camera["device_number"] in schedule_camera:
                            respText = "這台攝像機正在忙碌中, 請稍後～"
                            bot.send_message(chat_id=camera["chat_id"], text=respText, parse_mode="Markdown")
                            # 使用者請求清空
                            dbCameraControl.update_one({"device_number":camera["device_number"]}, {"$set":{"status":"0", "video_second":"", "chat_id":""}}, upsert=True)
                        else:
                            # 請求存入清單
                            schedule_camera.append(camera["device_number"])
                            # 平行處理
                            _thread.start_new_thread(video_job, (camera["chat_id"], camera["device_number"], camera["video_second"], url))
                else:
                    respText = "該位址無法連通, 請修正後重新嘗試～"
                    # 使用者請求清空, 連線狀態更改為異常(1)
                    dbCameraControl.update_one({"device_number":camera["device_number"]}, {"$set":{"status":"0", "video_second":"", "chat_id":"", "connection":"1"}}, upsert=True)
                    bot.send_message(chat_id=camera["chat_id"], text=respText, parse_mode="Markdown")
    func_CameraCreate()
    func_CameraControl()
main()

# 定時檢測, 每隔 10 秒執行 一次
schedule.every(10).seconds.do(main)

while True:
    schedule.run_pending()  
    time.sleep(1) 