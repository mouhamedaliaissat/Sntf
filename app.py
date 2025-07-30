import os
import logging
from datetime import datetime, time as dt_time, timedelta # Added for daily filtering
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
# --- Define the desired time format (hour:minute only) ---
REPORT_TIME_FORMAT = '%H:%M' # This format excludes date and seconds

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

# --- Helper function to get start and end of current day in Algeria timezone ---
def get_current_day_range_in_algeria():
    """Calculates the start (inclusive) and end (exclusive) timestamps for the current day in Algeria."""
    now_algeria = datetime.now(ALGERIA_TZ)
    # Start of today (00:00:00)
    start_of_day = datetime.combine(now_algeria.date(), dt_time.min).replace(tzinfo=ALGERIA_TZ)
    # Start of tomorrow (00:00:00) - acts as exclusive end for today
    end_of_day = datetime.combine(now_algeria.date(), dt_time.min).replace(tzinfo=ALGERIA_TZ) + timedelta(days=1)

    start_timestamp = start_of_day.timestamp()
    end_timestamp = end_of_day.timestamp()

    logger.info(f"📅 Calculated current day range: {start_of_day} ({start_timestamp}) to {end_of_day} ({end_timestamp})")
    return start_timestamp, end_timestamp

# --- Modified functions to filter by current day and optionally by direction ---

def get_all_reports_from_db_filtered(direction=None):
    """Retrieves reports filtered to today's date, optionally filtered by direction."""
    logger.info(f"📥 Retrieving TODAY'S reports from database (direction filter: {direction})...")
    try:
        if reports_collection is not None and MONGO_AVAILABLE:
            start_ts, end_ts = get_current_day_range_in_algeria()
            query = {"timestamp": {"$gte": start_ts, "$lt": end_ts}}
            if direction:
                query["direction"] = direction
            reports = list(reports_collection.find(query))
            logger.info(f"📊 Retrieved {len(reports)} reports from database (filtered to today, direction: {direction})")
            return reports
        else:
            logger.warning("⚠️ MongoDB collection not available for reading (filtered reports)")
            return []
    except Exception as e:
        logger.error(f"❌ Error getting filtered reports from MongoDB: {e}")
        logger.exception(e)
        return []

def get_reports_by_station_from_db_filtered(station, direction=None):
    """Retrieves reports for a specific station, filtered to today's date, optionally filtered by direction."""
    logger.info(f"📥 Retrieving TODAY'S reports for station: {station} (direction filter: {direction})")
    try:
        if reports_collection is not None and MONGO_AVAILABLE:
            start_ts, end_ts = get_current_day_range_in_algeria()
            query = {"station": station, "timestamp": {"$gte": start_ts, "$lt": end_ts}}
            if direction:
                 query["direction"] = direction
            reports = list(reports_collection.find(query))
            logger.info(f"📊 Retrieved {len(reports)} reports for station {station} (filtered to today, direction: {direction})")
            return reports
        else:
            logger.warning("⚠️ MongoDB collection not available for reading (filtered station reports)")
            return []
    except Exception as e:
        logger.error(f"❌ Error getting filtered reports by station from MongoDB: {e}")
        logger.exception(e)
        return []

# --- Helper function to group reports by minute ---
def group_reports_by_minute(reports):
    """
    Groups reports by station, direction, and minute.
    Returns a list of dictionaries with 'station', 'direction', 'time_str', and 'count'.
    """
    logger.info("🔄 Grouping reports by minute...")
    grouped = {}
    for report in reports:
        station = report["station"]
        direction = report["direction"]
        # Create a key based on station, direction, and the minute part of the timestamp
        report_time = datetime.fromtimestamp(report["timestamp"], ALGERIA_TZ)
        # Truncate seconds to get the minute key
        minute_key = report_time.replace(second=0, microsecond=0)
        key = (station, direction, minute_key)

        if key not in grouped:
            grouped[key] = {
                "station": station,
                "direction": direction,
                "time_str": minute_key.strftime(REPORT_TIME_FORMAT), # Format as HH:MM
                "count": 0
            }
        grouped[key]["count"] += 1

    # Convert the grouped dictionary values to a list and sort by time (newest first for display)
    result = sorted(grouped.values(), key=lambda x: x['time_str'], reverse=True)
    logger.info(f"📊 Grouped into {len(result)} entries.")
    return result

# Function to get all unique stations preserving order from schedules (used for reporting)
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
# Debug command (remains largely unchanged)
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
        [InlineKeyboardButton("🗣️ تواصل مع آخرين", url="https://t.me/+40I26LKN_0ZjYzY0")]
    ]
    if update.message:
        await update.message.reply_text("👋 مرحبًا بك! اختر خيارًا:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text("👋 مرحبًا بك! اختر خيارًا:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Helper functions for user-specific actions (remain unchanged) ---
def get_reports_by_user_id(user_id):
    """Get all reports created by a specific user ID"""
    logger.info(f"📥 Retrieving reports for user ID: {user_id}")
    try:
        if reports_collection is not None:
            reports = list(reports_collection.find({"user_id": str(user_id)}))
            logger.info(f"📊 Retrieved {len(reports)} reports for user {user_id}")
            return reports
        else:
            logger.warning("⚠️ MongoDB collection not available for reading (user reports)")
            return []
    except Exception as e:
        logger.error(f"❌ Error getting reports by user ID from MongoDB: {e}")
        logger.exception(e)
        return []

def delete_report_from_db(report_id):
    """Delete a report by its MongoDB ID"""
    logger.info(f"🗑️ Attempting to delete report with ID: {report_id}")
    try:
        if reports_collection is not None:
            from bson import ObjectId
            # Ensure report_id is a valid ObjectId string
            if not ObjectId.is_valid(report_id):
                logger.error(f"❌ Invalid ObjectId format: {report_id}")
                return False
            result = reports_collection.delete_one({"_id": ObjectId(report_id)})
            if result.deleted_count > 0:
                logger.info(f"✅ Successfully deleted report with ID: {report_id}")
                return True
            else:
                logger.warning(f"⚠️ No report found with ID: {report_id}")
                return False
        else:
            logger.warning("⚠️ MongoDB collection not available for deletion")
            return False
    except Exception as e:
        logger.error(f"❌ Error deleting report from MongoDB: {e}")
        logger.exception(e)
        return False

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        logger.info(f"🎮 Callback received: {query.data}")
        user_id = query.from_user.id # Get the user ID who clicked the button
        data = query.data
        # --- NEW DELETE REPORT FLOW ---
        # Handle request to view user's own reports for deletion
        if data == "delete_my_reports":
            logger.info(f"🗑️ User {user_id} requested to view their reports for deletion")
            user_reports = get_reports_by_user_id(user_id)
            if not user_reports:
                response = "❌ لم تقم بإنشاء أي تقارير بعد."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="report_train")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return
            response = "📋 تقاريرك:\n(انقر على التقرير لحذفه)\n"
            keyboard = []
            # Sort by timestamp (newest first) and show last 15
            sorted_reports = sorted(user_reports, key=lambda x: x["timestamp"], reverse=True)[:15]
            for i, report in enumerate(sorted_reports):
                station = report['station']
                direction_text = "الجزائر الى العفرون" if report["direction"] == DIRECTION_GO else "العفرون الى الجزائر"
                time_str = report['time'] # This will now be in the new format
                report_id = str(report['_id'])
                response += f"{i+1}. {station} | {direction_text} | {time_str}\n"
                # Button to delete this specific report
                keyboard.append([InlineKeyboardButton(f"🗑️ حذف {i+1}", callback_data=f"confirm_delete_my_report_{report_id}")])
            keyboard.append([InlineKeyboardButton("⬅️ العودة", callback_data="report_train")])
            await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
            return
        # Handle confirmation of deleting a user's own report
        elif data.startswith("confirm_delete_my_report_"):
            report_id = data.split("_", 4)[4]
            logger.info(f"🗑️ User {user_id} confirmed deletion of report {report_id}")
            success = delete_report_from_db(report_id)
            if success:
                response_text = "✅ تم حذف التقرير بنجاح!"
            else:
                response_text = "❌ فشل في حذف التقرير. قد يكون التقرير غير موجود."
            await query.edit_message_text(response_text)
            # Return to main menu after delay
            await asyncio.sleep(2)
            await start(update, context)
            return
        # --- END NEW DELETE REPORT FLOW ---
        # Report Train Arrival - Updated to include delete option
        if data == "report_train":
            logger.info("📝 User selected to report train arrival or manage reports")
            # Present options: report new arrival or delete existing reports
            keyboard = [
                [InlineKeyboardButton("➕ إبلاغ بوصول جديد", callback_data="report_new_arrival")],
                [InlineKeyboardButton("🗑️ حذف تقرير", callback_data="delete_my_reports")],
                [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
            ]
            await query.edit_message_text("اختر إجراء:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        # Sub-option for reporting a new arrival
        elif data == "report_new_arrival":
             logger.info("📝 User selected to report a *new* train arrival")
             stations = get_all_stations_ordered()
             logger.info(f"📊 Showing {len(stations)} stations for reporting")
             station_buttons = []
             for i in range(0, len(stations), 2):
                 row = []
                 row.append(InlineKeyboardButton(stations[i], callback_data=f"report_station_{stations[i]}"))
                 if i + 1 < len(stations):
                     row.append(InlineKeyboardButton(stations[i + 1], callback_data=f"report_station_{stations[i + 1]}"))
                 station_buttons.append(row)
             station_buttons.append([InlineKeyboardButton("⬅️ العودة", callback_data="report_train")])
             await query.edit_message_text("📍 اختر المحطة التي وصل إليها القطار:", reply_markup=InlineKeyboardMarkup(station_buttons))
             return
        elif data.startswith("report_station_"):
            station = data.split("_", 2)[2]
            context.user_data["report_station"] = station
            logger.info(f"📍 User selected station: {station}")
            keyboard = [
                [InlineKeyboardButton("🚆 الجزائر الى العفرون", callback_data="report_direction_go")],
                [InlineKeyboardButton("🚆 العفرون الى الجزائر", callback_data="report_direction_return")],
                [InlineKeyboardButton("⬅️ العودة", callback_data="report_train")] # Changed back button
            ]
            await query.edit_message_text(f"📍 المحطة: {station}\nاختر اتجاه القطار:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        elif data == "report_direction_go":
            station = context.user_data.get("report_station")
            direction = DIRECTION_GO
            logger.info(f"📤 Saving report - Station: {station}, Direction: {direction}, User: {user_id}")
            alg_time = get_algerian_time()
            report = {
                "station": station,
                "direction": direction,
                # --- Use the new time format (Hour:Minute only) ---
                "time": alg_time.strftime(REPORT_TIME_FORMAT), # Changed from '%Y-%m-%d %H:%M:%S'
                "timestamp": alg_time.timestamp(), # Keep timestamp for grouping/filtering
                "user_id": str(user_id) # Store the user ID who created the report
            }
            logger.info(f"📝 Report data: {report}")
            report_id = save_report_to_db(report) # Get the report ID
            if report_id:
                response_text = (f"✅ تم حفظ التقرير!\n"
                                 f"📍 المحطة: {station}\n"
                                 f"🧭 الاتجاه: الجزائر الى العفرون\n"
                                 f"🕐 الوقت: {report['time']}")
                logger.info(f"🎉 Report saved successfully for {station} with ID: {report_id} by user {user_id}")
            else:
                response_text = (f"❌ فشل حفظ التقرير!\n"
                                 f"📍 المحطة: {station}\n"
                                 f"🧭 الاتجاه: الجزائر الى العفرون\n"
                                 f"🕐 الوقت: {report['time']}\n"
                                 f"⚠️ مشكلة في الاتصال بقاعدة البيانات")
                logger.error(f"💥 Failed to save report for {station}")
            await query.edit_message_text(response_text)
            await asyncio.sleep(3)
            await start(update, context)
            return
        elif data == "report_direction_return":
            station = context.user_data.get("report_station")
            direction = DIRECTION_RETURN
            logger.info(f"📤 Saving report - Station: {station}, Direction: {direction}, User: {user_id}")
            alg_time = get_algerian_time()
            report = {
                "station": station,
                "direction": direction,
                 # --- Use the new time format (Hour:Minute only) ---
                "time": alg_time.strftime(REPORT_TIME_FORMAT), # Changed from '%Y-%m-%d %H:%M:%S'
                "timestamp": alg_time.timestamp(), # Keep timestamp for grouping/filtering
                "user_id": str(user_id) # Store the user ID who created the report
            }
            logger.info(f"📝 Report data: {report}")
            report_id = save_report_to_db(report) # Get the report ID
            if report_id:
                response_text = (f"✅ تم حفظ التقرير!\n"
                                 f"📍 المحطة: {station}\n"
                                 f"🧭 الاتجاه: العفرون الى الجزائر\n"
                                 f"🕐 الوقت: {report['time']}")
                logger.info(f"🎉 Report saved successfully for {station} with ID: {report_id} by user {user_id}")
            else:
                response_text = (f"❌ فشل حفظ التقرير!\n"
                                 f"📍 المحطة: {station}\n"
                                 f"🧭 الاتجاه: العفرون الى الجزائر\n"
                                 f"🕐 الوقت: {report['time']}\n"
                                 f"⚠️ مشكلة في الاتصال بقاعدة البيانات")
                logger.error(f"💥 Failed to save report for {station}")
            await query.edit_message_text(response_text)
            await asyncio.sleep(3)
            await start(update, context)
            return
        # View Reports - Ask for direction first
        elif data == "view_reports":
            logger.info("📋 User requested to view reports - asking for direction first")
            if not MONGO_AVAILABLE:
                response = "❌ قاعدة البيانات غير متوفرة حالياً."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                logger.warning("⚠️ View reports: MongoDB not available")
                return

            # Ask user to choose direction first
            keyboard = [
                [InlineKeyboardButton("🚆 الجزائر الى العفرون", callback_data="view_reports_direction_go")],
                [InlineKeyboardButton("🚆 العفرون الى الجزائر", callback_data="view_reports_direction_return")],
                [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
            ]
            await query.edit_message_text("🧭 اختر الاتجاه أولاً لعرض التقارير:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Handle direction selection for viewing reports (Sorting by Earliest Report Time)
        elif data in ["view_reports_direction_go", "view_reports_direction_return"]:
            chosen_direction = DIRECTION_GO if data == "view_reports_direction_go" else DIRECTION_RETURN
            context.user_data["view_direction"] = chosen_direction
            direction_text_display = "الجزائر الى العفرون" if chosen_direction == DIRECTION_GO else "العفرون الى الجزائر"
            logger.info(f"🧭 User selected direction: {direction_text_display} for viewing reports (sorted by time)")

            # 1. Get today's reports for the specific direction
            reports_today_direction = get_all_reports_from_db_filtered(direction=chosen_direction)

            if not reports_today_direction:
                response = "❌ لا توجد تقارير محفوظة لهذا اليوم في هذا الاتجاه."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return

            # 2. Group reports by station
            stations_with_reports = {}
            for report in reports_today_direction:
                station = report["station"]
                if station not in stations_with_reports:
                    stations_with_reports[station] = []
                stations_with_reports[station].append(report)

            # 3. Find the earliest report timestamp for each station
            station_earliest_times = {}
            for station, reports in stations_with_reports.items():
                # Find the report with the minimum timestamp for this station
                earliest_report = min(reports, key=lambda r: r['timestamp'])
                station_earliest_times[station] = earliest_report['timestamp']

            # 4. Sort stations based on their earliest report time (ascending order)
            sorted_stations_by_time = sorted(station_earliest_times.keys(), key=lambda s: station_earliest_times[s])

            logger.info(f"📊 Found {len(sorted_stations_by_time)} stations with reports for direction {chosen_direction} (sorted by earliest time)")

            # 5. Create station buttons based on the time-sorted list
            station_buttons = []
            for i in range(0, len(sorted_stations_by_time), 2):
                row = []
                station1 = sorted_stations_by_time[i]
                report_count1 = len(stations_with_reports[station1])
                row.append(InlineKeyboardButton(f"📍 {station1} ({report_count1})", callback_data=f"view_station_filtered_{station1}"))
                if i + 1 < len(sorted_stations_by_time):
                    station2 = sorted_stations_by_time[i + 1]
                    report_count2 = len(stations_with_reports[station2])
                    row.append(InlineKeyboardButton(f"📍 {station2} ({report_count2})", callback_data=f"view_station_filtered_{station2}"))
                station_buttons.append(row)
            station_buttons.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])

            await query.edit_message_text(f"📋 اختر محطة لعرض تقارير اليوم ({direction_text_display}) مرتبة حسب وقت التقرير:", reply_markup=InlineKeyboardMarkup(station_buttons))
            return

        # View Station Reports (Filtered by previously selected direction)
        elif data.startswith("view_station_filtered_"):
            selected_station = data.split("_", 3)[3]
            chosen_direction = context.user_data.get("view_direction")
            logger.info(f"🔍 User viewing TODAY'S reports for station: {selected_station} in direction: {chosen_direction}")

            if not chosen_direction:
                 logger.warning("⚠️ View station filtered: No direction selected in user_data")
                 await query.edit_message_text("❌ حدث خطأ. يرجى المحاولة مرة أخرى من البداية.")
                 return

            if not MONGO_AVAILABLE:
                response = "❌ قاعدة البيانات غير متوفرة حالياً."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return

            # Get filtered reports for the station AND the chosen direction for TODAY
            station_reports_raw = get_reports_by_station_from_db_filtered(station=selected_station, direction=chosen_direction)

            if not station_reports_raw:
                direction_text_display = "الجزائر الى العفرون" if chosen_direction == DIRECTION_GO else "العفرون الى الجزائر"
                response = f"❌ لا توجد تقارير لهذا اليوم للمحطة: {selected_station} في اتجاه {direction_text_display}"
            else:
                # Group the raw reports by minute
                grouped_reports_list = group_reports_by_minute(station_reports_raw)

                if not grouped_reports_list:
                     response = f"❌ لا توجد تقارير لهذا اليوم للمحطة: {selected_station} في هذا الاتجاه (بعد التجميع)"
                else:
                    direction_text_header = "الجزائر الى العفرون" if chosen_direction == DIRECTION_GO else "العفرون الى الجزائر"
                    response = f"📋 تقارير اليوم للمحطة: {selected_station} ({direction_text_header})\n"
                    # Show last 10 grouped entries (already sorted by time, newest first)
                    for i, grouped_report in enumerate(grouped_reports_list[:10]):
                        # Note: Direction is already filtered, so no need to check again
                        time_str = grouped_report['time_str']
                        count = grouped_report['count']
                        # Add checkmark and count if more than one
                        count_display = f" ✅ ({count})" if count > 1 else ""
                        response += f"{i+1}. 🕐 {time_str}{count_display}\n"

            # Update back button logic to go back to direction selection
            keyboard = [
                [InlineKeyboardButton("📋 عرض محطات أخرى", callback_data=f"view_reports_direction_{chosen_direction}")], # Go back to station list for the same direction
                [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
            ]
            await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
            return
        # Original functionality (remains unchanged)
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
