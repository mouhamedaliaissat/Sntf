import os
import logging
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from schedules import go_schedule, return_schedule
from pymongo import MongoClient, errors
import asyncio

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set Algerian time zone
ALGERIA_TZ = pytz.timezone('Africa/Algiers')

# Constants
DIRECTION_GO = "go"
DIRECTION_RETURN = "return"

# MongoDB setup
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = "train_bot"
COLLECTION_NAME = "reports"

# Initialize MongoDB client with error handling
client = None
reports_collection = None
MONGO_AVAILABLE = False

def init_mongodb():
    global client, reports_collection, MONGO_AVAILABLE
    logger.info("🔧 Starting MongoDB initialization...")
    if not MONGODB_URI:
        logger.error("❌ MONGODB_URI environment variable not set")
        return False
    try:
        logger.info(f"🔧 Attempting to connect to MongoDB...")
        logger.info(f"🔗 URI: {MONGODB_URI[:30]}...{MONGODB_URI[-20:] if len(MONGODB_URI) > 50 else MONGODB_URI}")
        logger.info(f"MONGODB_URI is: {MONGODB_URI}")
        # Create client with timeout settings
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000
        )
        # Test the connection
        logger.info("🔍 Testing MongoDB connection...")
        client.admin.command('ping')
        logger.info("✅ MongoDB ping successful")
        # Access database and collection
        db = client[DB_NAME]
        reports_collection = db[COLLECTION_NAME]
        logger.info(f"📚 Using database: {DB_NAME}, collection: {COLLECTION_NAME}")
        # Test insert to verify everything works
        test_doc = {
            "test": "connection",
            "time": datetime.now().timestamp(),
            "source": "bot_initialization"
        }
        logger.info("📝 Testing document insertion...")
        result = reports_collection.insert_one(test_doc)
        logger.info(f"✅ Test document inserted with ID: {result.inserted_id}")
        # Clean up test document
        reports_collection.delete_one({"_id": result.inserted_id})
        logger.info("🧹 Test document cleaned up")
        MONGO_AVAILABLE = True
        logger.info("🎉 MongoDB initialization completed successfully")
        return True
    except errors.ServerSelectionTimeoutError as e:
        logger.error(f"❌ MongoDB connection timeout: {e}")
        logger.error("💡 Check your internet connection and MongoDB URI")
    except errors.ConnectionFailure as e:
        logger.error(f"❌ MongoDB connection failure: {e}")
        logger.error("💡 Check if MongoDB Atlas cluster is running")
    except errors.ConfigurationError as e:
        logger.error(f"❌ MongoDB configuration error: {e}")
        logger.error("💡 Check your MongoDB URI format")
    except errors.AuthenticationFailed as e:
        logger.error(f"❌ MongoDB authentication failed: {e}")
        logger.error("💡 Check your username and password")
    except Exception as e:
        logger.error(f"❌ Unexpected error during MongoDB initialization: {e}")
        logger.exception(e)
    return False

# Initialize MongoDB on startup
logger.info("🚀 Initializing MongoDB connection...")
MONGO_AVAILABLE = init_mongodb()
logger.info(f"📊 MongoDB Status: {'🟢 Available' if MONGO_AVAILABLE else '🔴 Not Available'}")

# Function to get all unique stations preserving order from schedules
def get_all_stations_ordered():
    logger.info("📋 Getting all stations in order...")
    go_stations = list(go_schedule.keys())
    return_stations = list(return_schedule.keys())
    all_stations = []
    seen = set()
    # Add stations from go_schedule first
    for station in go_stations:
        if station not in seen:
            all_stations.append(station)
            seen.add(station)
    # Add stations from return_schedule
    for station in return_stations:
        if station not in seen:
            all_stations.append(station)
            seen.add(station)
    logger.info(f"📊 Total stations found: {len(all_stations)}")
    return all_stations

def get_algerian_time():
    return datetime.now(ALGERIA_TZ)

def save_report_to_db(report_data):
    logger.info(f"💾 Attempting to save report to database: {report_data}")
    try:
        if reports_collection is not None:
            logger.info("📤 Inserting document into MongoDB...")
            result = reports_collection.insert_one(report_data)
            logger.info(f"✅ Report saved successfully with ID: {result.inserted_id}")
            # Return the ID as a string for use in callback_data
            return str(result.inserted_id)
        else:
            logger.warning("⚠️ MongoDB collection not available for saving")
            return None
    except Exception as e:
        logger.error(f"❌ Error saving report to MongoDB: {e}")
        logger.exception(e)
        return None

def get_all_reports_from_db():
    logger.info("📥 Retrieving all reports from database...")
    try:
        if reports_collection is not None:
            reports = list(reports_collection.find())
            logger.info(f"📊 Retrieved {len(reports)} reports from database")
            return reports
        else:
            logger.warning("⚠️ MongoDB collection not available for reading")
            return []
    except Exception as e:
        logger.error(f"❌ Error getting reports from MongoDB: {e}")
        logger.exception(e)
        return []

def get_reports_by_station_from_db(station):
    logger.info(f"📥 Retrieving reports for station: {station}")
    try:
        if reports_collection is not None:
            reports = list(reports_collection.find({"station": station}))
            logger.info(f"📊 Retrieved {len(reports)} reports for station {station}")
            return reports
        else:
            logger.warning("⚠️ MongoDB collection not available for reading")
            return []
    except Exception as e:
        logger.error(f"❌ Error getting reports by station from MongoDB: {e}")
        logger.exception(e)
        return []

def delete_report_from_db(report_id, user_id):
    """Delete a report by its MongoDB ID, checking user ID"""
    logger.info(f"🗑️ Attempting to delete report with ID: {report_id} by user: {user_id}")
    try:
        if reports_collection is not None:
            from bson import ObjectId
            # Ensure report_id is a valid ObjectId string
            if not ObjectId.is_valid(report_id):
                logger.error(f"❌ Invalid ObjectId format: {report_id}")
                return False
            # Find the report and check the user_id
            report = reports_collection.find_one({"_id": ObjectId(report_id)})
            if not report:
                logger.warning(f"⚠️ No report found with ID: {report_id}")
                return False

            if str(report.get("user_id")) != str(user_id):
                logger.warning(f"⚠️ User {user_id} is not authorized to delete report {report_id}")
                return False # Not authorized

            # If user matches, proceed with deletion
            result = reports_collection.delete_one({"_id": ObjectId(report_id)})
            if result.deleted_count > 0:
                logger.info(f"✅ Successfully deleted report with ID: {report_id}")
                return True
            else:
                # This case should be rare if the report existed
                logger.warning(f"⚠️ No report found with ID: {report_id} (during deletion)")
                return False
        else:
            logger.warning("⚠️ MongoDB collection not available for deletion")
            return False
    except Exception as e:
        logger.error(f"❌ Error deleting report from MongoDB: {e}")
        logger.exception(e)
        return False

# Debug command
async def debug_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check database status"""
    logger.info("🔍 Debug command received")
    if not MONGO_AVAILABLE:
        response = "❌ MongoDB not available\n"
        response += "Check Railway logs for connection errors"
        await update.message.reply_text(response)
        logger.warning("⚠️ Debug command: MongoDB not available")
        return
    try:
        logger.info("🔍 Performing debug checks...")
        # Check connection
        logger.info("🔍 Testing MongoDB connection...")
        client.admin.command('ping')
        logger.info("✅ MongoDB connection test successful")
        # Get database info
        logger.info("🔍 Getting database information...")
        db_names = client.list_database_names()
        logger.info(f"📊 Available databases: {db_names}")
        collection_names = reports_collection.database.list_collection_names()
        logger.info(f"📂 Available collections: {collection_names}")
        # Get report count
        logger.info("🔍 Counting reports...")
        report_count = reports_collection.count_documents({})
        logger.info(f"📈 Total reports in database: {report_count}")
        # Get sample reports
        logger.info("🔍 Getting sample reports...")
        sample_reports = list(reports_collection.find().limit(3))
        logger.info(f"📋 Sample reports retrieved: {len(sample_reports)}")
        response = "✅ Database Debug Information:\n"
        response += f"📊 Databases: {db_names}\n"
        response += f"📂 Collections: {collection_names}\n"
        response += f"📈 Total Reports: {report_count}\n"
        if sample_reports:
            response += "📋 Recent Reports:\n"
            for i, report in enumerate(sample_reports[:3]):
                response += f"{i+1}. {report.get('station', 'N/A')} - {report.get('direction', 'N/A')} - {report.get('time', 'N/A')}\n"
        else:
            response += "📭 No reports found\n"
        response += "🔧 MongoDB Status: Connected ✅"
        await update.message.reply_text(response)
        logger.info("✅ Debug command completed successfully")
    except Exception as e:
        logger.error(f"❌ Debug command error: {e}")
        logger.exception(e)
        await update.message.reply_text(f"❌ Database Error: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("🏠 Start command received")
    keyboard = [
        [InlineKeyboardButton("🚆 الجزائر الى العفرون", callback_data="direction_go")],
        [InlineKeyboardButton("🚆 العفرون الى الجزائر", callback_data="direction_return")],
        [InlineKeyboardButton("📊 إبلاغ بوصول قطار", callback_data="report_train")],
        [InlineKeyboardButton("📋 عرض التقارير", callback_data="view_reports")]
    ]
    if update.message:
        await update.message.reply_text("👋 مرحبًا بك! اختر خيارًا:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text("👋 مرحبًا بك! اختر خيارًا:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        logger.info(f"🎮 Callback received: {query.data}")
        user_id = query.from_user.id # Get the user ID who clicked the button
        data = query.data

        # --- DELETE REPORT FUNCTIONALITY ---
        # Handle delete report request (shows confirmation)
        if data.startswith("delete_report_"):
            report_id = data.split("_", 2)[2]

            # Show confirmation dialog
            keyboard = [
                [InlineKeyboardButton("✅ نعم، احذف", callback_data=f"confirm_delete_{report_id}")],
                [InlineKeyboardButton("❌ إلغاء", callback_data=f"cancel_delete_{report_id}")]
            ]
            await query.edit_message_text("⚠️ هل أنت متأكد أنك تريد حذف هذا التقرير؟", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Handle delete report confirmation
        elif data.startswith("confirm_delete_"):
            report_id = data.split("_", 2)[2]
            # Delete the report, passing the user ID for authorization check
            success = delete_report_from_db(report_id, user_id)
            if success:
                response_text = "✅ تم حذف التقرير بنجاح!"
            else:
                response_text = "❌ فشل في حذف التقرير. قد يكون التقرير غير موجود أو ليس لديك الصلاحية لحذفه."

            await query.edit_message_text(response_text)
            # Return to main menu after delay
            await asyncio.sleep(2)
            await start(update, context)
            return

        # Handle delete report cancellation
        elif data.startswith("cancel_delete_"):
            report_id = data.split("_", 2)[2]
            # Show the report details again by going back to the station view
            if not MONGO_AVAILABLE or reports_collection is None:
                await query.edit_message_text("❌ قاعدة البيانات غير متوفرة.")
                return

            try:
                from bson import ObjectId
                if not ObjectId.is_valid(report_id):
                    await query.edit_message_text("❌ معرف التقرير غير صالح.")
                    return

                report = reports_collection.find_one({"_id": ObjectId(report_id)})
                if report:
                    # Find the station and redirect to view_station_ for that station
                    station = report['station']
                    logger.info(f"🔍 User viewing reports for station (after cancel): {station}")
                    # Re-display the station reports view
                    station_reports = get_reports_by_station_from_db(station)
                    if not station_reports:
                         response = f"❌ لا توجد تقارير للمحطة: {station}"
                         keyboard = [
                             [InlineKeyboardButton("📋 عرض محطات أخرى", callback_data="view_reports")],
                             [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
                         ]
                    else:
                        response = f"📋 تقارير المحطة: {station}\n\n"
                        # Sort by timestamp (newest first) and show last 10
                        sorted_reports = sorted(station_reports, key=lambda x: x["timestamp"], reverse=True)[:10]

                        # Create the keyboard with delete buttons (conditionally)
                        keyboard = []
                        for i, rpt in enumerate(sorted_reports):
                            direction_text = "الجزائر الى العفرون" if rpt["direction"] == DIRECTION_GO else "العفرون الى الجزائر"
                            response += f"{i+1}. 🧭 {direction_text}\n   🕐 {rpt['time']}\n"

                            # Add delete button for each report if the user is the creator
                            rpt_id = str(rpt['_id'])
                            rpt_creator_id = str(rpt.get('user_id', '')) # Get creator ID from DB
                            if str(user_id) == rpt_creator_id:
                                keyboard.append([InlineKeyboardButton("🗑️ حذف", callback_data=f'delete_report_{rpt_id}')])
                            else:
                                response += "   (ليس لك)\n" # Indicate not owned by user
                            response += "\n" # Add space after each report block

                        # Add navigation buttons at the end
                        keyboard.append([InlineKeyboardButton("📋 عرض محطات أخرى", callback_data="view_reports")])
                        keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])

                    await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    await query.edit_message_text("❌ التقرير غير موجود.")
            except Exception as e:
                logger.error(f"❌ Error retrieving report after cancel: {e}")
                logger.exception(e)
                await query.edit_message_text("❌ حدث خطأ أثناء استرجاع التقرير.")
            return
        # --- END DELETE REPORT FUNCTIONALITY ---

        # Report Train Arrival
        if data == "report_train":
            logger.info("📝 User selected to report train arrival")
            stations = get_all_stations_ordered()
            logger.info(f"📊 Showing {len(stations)} stations for reporting")
            station_buttons = []
            for i in range(0, len(stations), 2):
                row = []
                row.append(InlineKeyboardButton(stations[i], callback_data=f"report_station_{stations[i]}"))
                if i + 1 < len(stations):
                    row.append(InlineKeyboardButton(stations[i + 1], callback_data=f"report_station_{stations[i + 1]}"))
                station_buttons.append(row)
            station_buttons.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])
            await query.edit_message_text("📍 اختر المحطة التي وصل إليها القطار:", reply_markup=InlineKeyboardMarkup(station_buttons))
            return

        elif data.startswith("report_station_"):
            station = data.split("_", 2)[2]
            context.user_data["report_station"] = station
            logger.info(f"📍 User selected station: {station}")
            keyboard = [
                [InlineKeyboardButton("🚆 الجزائر الى العفرون", callback_data="report_direction_go")],
                [InlineKeyboardButton("🚆 العفرون الى الجزائر", callback_data="report_direction_return")],
                [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
            ]
            await query.edit_message_text(f"📍 المحطة: {station}\nاختر اتجاه القطار:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        elif data == "report_direction_go":
            station = context.user_data.get("report_station")
            direction = DIRECTION_GO
            logger.info(f"📤 Saving report - Station: {station}, Direction: {direction}")
            alg_time = get_algerian_time()
            report = {
                "station": station,
                "direction": direction,
                "time": alg_time.strftime('%Y-%m-%d %H:%M:%S'),
                "timestamp": alg_time.timestamp(),
                "user_id": user_id # Store the user ID who created the report
            }
            logger.info(f"📝 Report data: {report}")
            report_id = save_report_to_db(report) # Get the report ID
            if report_id:
                response_text = f"✅ تم حفظ التقرير!\n📍 المحطة: {station}\n🧭 الاتجاه: الجزائر الى العفرون\n🕐 الوقت: {report['time']}"
                logger.info(f"🎉 Report saved successfully for {station} with ID: {report_id} by user {user_id}")
            else:
                response_text = f"❌ فشل حفظ التقرير!\n📍 المحطة: {station}\n🧭 الاتجاه: الجزائر الى العفرون\n🕐 الوقت: {report['time']}\n⚠️ مشكلة في الاتصال بقاعدة البيانات"
                logger.error(f"💥 Failed to save report for {station}")
            await query.edit_message_text(response_text)
            await asyncio.sleep(3)
            await start(update, context)
            return

        elif data == "report_direction_return":
            station = context.user_data.get("report_station")
            direction = DIRECTION_RETURN
            logger.info(f"📤 Saving report - Station: {station}, Direction: {direction}")
            alg_time = get_algerian_time()
            report = {
                "station": station,
                "direction": direction,
                "time": alg_time.strftime('%Y-%m-%d %H:%M:%S'),
                "timestamp": alg_time.timestamp(),
                "user_id": user_id # Store the user ID who created the report
            }
            logger.info(f"📝 Report data: {report}")
            report_id = save_report_to_db(report) # Get the report ID
            if report_id:
                response_text = f"✅ تم حفظ التقرير!\n📍 المحطة: {station}\n🧭 الاتجاه: العفرون الى الجزائر\n🕐 الوقت: {report['time']}"
                logger.info(f"🎉 Report saved successfully for {station} with ID: {report_id} by user {user_id}")
            else:
                response_text = f"❌ فشل حفظ التقرير!\n📍 المحطة: {station}\n🧭 الاتجاه: العفرون الى الجزائر\n🕐 الوقت: {report['time']}\n⚠️ مشكلة في الاتصال بقاعدة البيانات"
                logger.error(f"💥 Failed to save report for {station}")
            await query.edit_message_text(response_text)
            await asyncio.sleep(3)
            await start(update, context)
            return

        # View Reports
        elif data == "view_reports":
            logger.info("📋 User requested to view reports")
            if not MONGO_AVAILABLE:
                response = "❌ قاعدة البيانات غير متوفرة حالياً."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                logger.warning("⚠️ View reports: MongoDB not available")
                return
            reports = get_all_reports_from_db()
            logger.info(f"📊 Found {len(reports)} total reports")
            if not reports:
                response = "❌ لا توجد تقارير محفوظة."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return
            stations_with_reports = {}
            for report in reports:
                station = report["station"]
                if station not in stations_with_reports:
                    stations_with_reports[station] = []
                stations_with_reports[station].append(report)
            all_stations = get_all_stations_ordered()
            station_buttons = []
            stations_with_reports_ordered = [station for station in all_stations if station in stations_with_reports]
            logger.info(f"📊 Stations with reports: {len(stations_with_reports_ordered)}")
            if not stations_with_reports_ordered:
                response = "❌ لا توجد تقارير محفوظة."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return
            for i in range(0, len(stations_with_reports_ordered), 2):
                row = []
                station1 = stations_with_reports_ordered[i]
                report_count1 = len(stations_with_reports[station1])
                row.append(InlineKeyboardButton(f"📍 {station1} ({report_count1})", callback_data=f"view_station_{station1}"))
                if i + 1 < len(stations_with_reports_ordered):
                    station2 = stations_with_reports_ordered[i + 1]
                    report_count2 = len(stations_with_reports[station2])
                    row.append(InlineKeyboardButton(f"📍 {station2} ({report_count2})", callback_data=f"view_station_{station2}"))
                station_buttons.append(row)
            station_buttons.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])
            await query.edit_message_text("📋 اختر محطة لعرض التقارير:", reply_markup=InlineKeyboardMarkup(station_buttons))
            return

        elif data.startswith("view_station_"):
            selected_station = data.split("_", 2)[2]
            logger.info(f"🔍 User viewing reports for station: {selected_station}")
            if not MONGO_AVAILABLE:
                response = "❌ قاعدة البيانات غير متوفرة حالياً."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return
            station_reports = get_reports_by_station_from_db(selected_station)
            if not station_reports:
                response = f"❌ لا توجد تقارير للمحطة: {selected_station}"
                keyboard = [
                    [InlineKeyboardButton("📋 عرض محطات أخرى", callback_data="view_reports")],
                    [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
                ]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                response = f"📋 تقارير المحطة: {selected_station}\n\n"
                # Sort by timestamp (newest first) and show last 10
                sorted_reports = sorted(station_reports, key=lambda x: x["timestamp"], reverse=True)[:10]

                # Create the keyboard with delete buttons (conditionally)
                keyboard = []
                for i, report in enumerate(sorted_reports):
                    direction_text = "الجزائر الى العفرون" if report["direction"] == DIRECTION_GO else "العفرون الى الجزائر"
                    response += f"{i+1}. 🧭 {direction_text}\n   🕐 {report['time']}\n"

                    # Add delete button for each report if the user is the creator
                    report_id = str(report['_id'])
                    report_creator_id = str(report.get('user_id', '')) # Get creator ID from DB
                    if str(user_id) == report_creator_id:
                        keyboard.append([InlineKeyboardButton("🗑️ حذف", callback_data=f'delete_report_{report_id}')])
                    else:
                        response += "   (ليس لك)\n" # Indicate not owned by user
                    response += "\n" # Add space after each report block

                # Add navigation buttons at the end
                keyboard.append([InlineKeyboardButton("📋 عرض محطات أخرى", callback_data="view_reports")])
                keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])

                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Original functionality
        elif data == "direction_go":
            context.user_data["direction"] = DIRECTION_GO
            stations = list(go_schedule.keys())
            station_buttons = [
                [InlineKeyboardButton(station, callback_data=f"station_{station}")]
                for station in stations
            ]
            station_buttons.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])
            await query.edit_message_text("📍 اختر محطتك:", reply_markup=InlineKeyboardMarkup(station_buttons))
            return

        elif data == "direction_return":
            context.user_data["direction"] = DIRECTION_RETURN
            stations = list(return_schedule.keys())
            station_buttons = [
                [InlineKeyboardButton(station, callback_data=f"station_{station}")]
                for station in stations
            ]
            station_buttons.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])
            await query.edit_message_text("📍 اختر محطتك:", reply_markup=InlineKeyboardMarkup(station_buttons))
            return

        elif data == "back_to_start":
            await start(update, context)
            return

        elif data == "show_all_trains":
            station = context.user_data.get("last_station")
            direction = context.user_data.get("direction")
            if direction == DIRECTION_GO:
                schedule = go_schedule.get(station, [])
                destination = "العفرون"
            else:
                schedule = return_schedule.get(station, [])
                destination = "الجزائر"
            now = get_algerian_time().time()

            def str_to_time(s):
                return datetime.strptime(s, "%H:%M").time()

            future_trains = [t for t in schedule if str_to_time(t) > now]
            if future_trains:
                train_list = "\n".join([f"🚆 {time}" for time in future_trains])
                response = f"جميع القطارات القادمة من {station} إلى {destination}:\n{train_list}"
            else:
                response = f"❌ لا يوجد قطارات متبقية اليوم من {station} إلى {destination}."
            keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
            await query.edit_message_text(text=response, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        elif data.startswith("station_"):
            station = data.split("_", 1)[1]
            context.user_data["last_station"] = station
            direction = context.user_data.get("direction")
            now = get_algerian_time().time()

            def str_to_time(s):
                return datetime.strptime(s, "%H:%M").time()

            if direction == DIRECTION_GO:
                schedule = go_schedule.get(station, [])
                destination = "العفرون"
            else:
                schedule = return_schedule.get(station, [])
                destination = "الجزائر"
            next_train = next((t for t in schedule if str_to_time(t) > now), None)
            if next_train:
                response = f"🚉 القطار الآتي من {station} إلى {destination} ينطلق على الساعة {next_train}."
                keyboard = [
                    [InlineKeyboardButton("عرض جميع القطارات القادمة", callback_data="show_all_trains")],
                    [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
                ]
            else:
                response = f"❌ لا يوجد قطارات متبقية اليوم من {station} إلى {destination}."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
            await query.edit_message_text(text=response, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        else:
            await query.edit_message_text("❗ أمر غير معروف.")
            return

    except Exception as e:
        logger.error(f"❌ Error in callback handler: {e}")
        logger.exception(e)
        try:
            await update.callback_query.edit_message_text("❌ حدث خطأ، يرجى المحاولة مرة أخرى.")
        except:
            pass

def main():
    logger.info("🚀 Starting Train Schedule Bot...")
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN not set in environment variables.")
        return
    try:
        logger.info(f"📊 MongoDB Status at startup: {'🟢 Available' if MONGO_AVAILABLE else '🔴 Not Available'}")
        if MONGO_AVAILABLE and reports_collection is not None:
            try:
                count = reports_collection.count_documents({})
                logger.info(f"📈 Current reports in database: {count}")
            except Exception as e:
                logger.error(f"❌ Error counting documents at startup: {e}")
        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("debug", debug_db))
        app.add_handler(CallbackQueryHandler(handle_callback))
        logger.info("✅ Train Schedule Bot is running with Algeria timezone and MongoDB...")
        app.run_polling()
    except Exception as e:
        logger.error(f"❌ Bot failed to start: {e}")
        logger.exception(e)
        raise

if __name__ == '__main__':
    main()
