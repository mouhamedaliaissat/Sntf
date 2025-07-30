import os
import logging
from datetime import datetime, time as dt_time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from schedules import go_schedule, return_schedule
from pymongo import MongoClient, errors
import asyncio

# ... (rest of the imports and initial setup remain the same) ...

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

# --- Modified functions to filter by current day ---

def get_all_reports_from_db(filter_today=True):
    """Retrieves all reports, optionally filtered to today's date."""
    logger.info(f"📥 Retrieving reports from database (filter_today={filter_today})...")
    try:
        if reports_collection is not None:
            query = {}
            if filter_today:
                start_ts, end_ts = get_current_day_range_in_algeria()
                query["timestamp"] = {"$gte": start_ts, "$lt": end_ts}

            reports = list(reports_collection.find(query))
            logger.info(f"📊 Retrieved {len(reports)} reports from database (filtered: {filter_today})")
            return reports
        else:
            logger.warning("⚠️ MongoDB collection not available for reading")
            return []
    except Exception as e:
        logger.error(f"❌ Error getting reports from MongoDB: {e}")
        logger.exception(e)
        return []

def get_reports_by_station_from_db(station, filter_today=True):
    """Retrieves reports for a specific station, optionally filtered to today's date."""
    logger.info(f"📥 Retrieving reports for station: {station} (filter_today={filter_today})")
    try:
        if reports_collection is not None:
            query = {"station": station}
            if filter_today:
                start_ts, end_ts = get_current_day_range_in_algeria()
                query["timestamp"] = {"$gte": start_ts, "$lt": end_ts}

            reports = list(reports_collection.find(query))
            logger.info(f"📊 Retrieved {len(reports)} reports for station {station} (filtered: {filter_today})")
            return reports
        else:
            logger.warning("⚠️ MongoDB collection not available for reading")
            return []
    except Exception as e:
        logger.error(f"❌ Error getting reports by station from MongoDB: {e}")
        logger.exception(e)
        return []

# --- Keep existing functions like get_reports_by_user_id and delete_report_from_db as they are ---
# They are used for user-specific actions and deletion, not necessarily the public view.

# --- Modified handle_callback logic for viewing reports ---

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        logger.info(f"🎮 Callback received: {query.data}")
        user_id = query.from_user.id
        data = query.data

        # ... (other callback logic like reporting, deleting user reports remains unchanged) ...

        # View Reports (Public view - now filtered to today)
        elif data == "view_reports":
            logger.info("📋 User requested to view TODAY'S reports")
            if not MONGO_AVAILABLE:
                response = "❌ قاعدة البيانات غير متوفرة حالياً."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                logger.warning("⚠️ View reports: MongoDB not available")
                return
            # Use the modified function with filter enabled
            reports = get_all_reports_from_db(filter_today=True)
            logger.info(f"📊 Found {len(reports)} reports for today")

            if not reports:
                response = "❌ لا توجد تقارير محفوظة لهذا اليوم."
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
            # Ensure stations are ordered based on their appearance in schedules AND having reports today
            stations_with_reports_ordered = [station for station in all_stations if station in stations_with_reports]
            logger.info(f"📊 Stations with reports today: {len(stations_with_reports_ordered)}")

            if not stations_with_reports_ordered:
                response = "❌ لا توجد تقارير محفوظة لهذا اليوم."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return

            station_buttons = []
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
            await query.edit_message_text("📋 اختر محطة لعرض تقارير اليوم:", reply_markup=InlineKeyboardMarkup(station_buttons))
            return

        elif data.startswith("view_station_"):
            selected_station = data.split("_", 2)[2]
            logger.info(f"🔍 User viewing TODAY'S reports for station: {selected_station}")
            if not MONGO_AVAILABLE:
                response = "❌ قاعدة البيانات غير متوفرة حالياً."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return
            # Use the modified function with filter enabled
            station_reports = get_reports_by_station_from_db(selected_station, filter_today=True)

            if not station_reports:
                response = f"❌ لا توجد تقارير لهذا اليوم للمحطة: {selected_station}"
            else:
                response = f"📋 تقارير اليوم للمحطة: {selected_station}\n" # Updated message
                # Sort by timestamp (newest first) and show last 10 (of today)
                sorted_reports = sorted(station_reports, key=lambda x: x["timestamp"], reverse=True)[:10]
                for i, report in enumerate(sorted_reports):
                    direction_text = "الجزائر الى العفرون" if report["direction"] == DIRECTION_GO else "العفرون الى الجزائر"
                    response += f"{i+1}. 🧭 {direction_text}\n   🕐 {report['time']}\n"

            keyboard = [
                [InlineKeyboardButton("📋 عرض محطات أخرى", callback_data="view_reports")],
                [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
            ]
            await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # ... (rest of the callback logic like schedules remains unchanged) ...

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

# ... (rest of the code like get_algerian_time, save_report_to_db, init_mongodb, main remains the same) ...

# Make sure to import timedelta
from datetime import timedelta

if __name__ == '__main__':
    main()
