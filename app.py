import os
import logging
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from schedules import go_schedule, return_schedule
import json

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
USER_DATA_FILE = "user_data.json"

# Function to get Algerian time
def get_algerian_time():
    return datetime.now(ALGERIA_TZ)

# Function to save user data
def save_user_data(data):
    try:
        with open(USER_DATA_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

# Function to load user data
def load_user_data():
    try:
        with open(USER_DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"Error loading user data: {e}")
        return {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚆 الجزائر → العفرون", callback_data="direction_go")],
        [InlineKeyboardButton("🚆 العفرون → الجزائر", callback_data="direction_return")],
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

        data = query.data
        
        # Report Train Arrival
        if data == "report_train":
            stations = list(set(list(go_schedule.keys()) + list(return_schedule.keys())))
            station_buttons = [
                [InlineKeyboardButton(station, callback_data=f"report_station_{station}")]
                for station in stations[:10]  # Limit to 10 stations per page
            ]
            if len(stations) > 10:
                # Add more stations in second column if needed
                pass
            station_buttons.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])
            await query.edit_message_text("📍 اختر المحطة التي وصل إليها القطار:", reply_markup=InlineKeyboardMarkup(station_buttons))
            return
            
        elif data.startswith("report_station_"):
            station = data.split("_", 3)[2]
            context.user_data["report_station"] = station
            
            # Choose direction
            keyboard = [
                [InlineKeyboardButton("🚆 الجزائر → العفرون", callback_data="report_direction_go")],
                [InlineKeyboardButton("🚆 العفرون → الجزائر", callback_data="report_direction_return")],
                [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
            ]
            await query.edit_message_text(f"📍 المحطة: {station}\nاختر اتجاه القطار:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
            
        elif data == "report_direction_go":
            station = context.user_data.get("report_station")
            direction = DIRECTION_GO
            
            # Save report
            user_data = load_user_data()
            if "reports" not in user_data:
                user_data["reports"] = []
            
            report = {
                "station": station,
                "direction": direction,
                "time": get_algerian_time().strftime('%Y-%m-%d %H:%M:%S'),
                "timestamp": get_algerian_time().timestamp()
            }
            user_data["reports"].append(report)
            save_user_data(user_data)
            
            await query.edit_message_text(f"✅ تم حفظ التقرير!\n📍 المحطة: {station}\n🧭 الاتجاه: الجزائر → العفرون\n🕐 الوقت: {report['time']}")
            # Show main menu after 3 seconds
            await asyncio.sleep(3)
            await start(update, context)
            return
            
        elif data == "report_direction_return":
            station = context.user_data.get("report_station")
            direction = DIRECTION_RETURN
            
            # Save report
            user_data = load_user_data()
            if "reports" not in user_data:
                user_data["reports"] = []
            
            report = {
                "station": station,
                "direction": direction,
                "time": get_algerian_time().strftime('%Y-%m-%d %H:%M:%S'),
                "timestamp": get_algerian_time().timestamp()
            }
            user_data["reports"].append(report)
            save_user_data(user_data)
            
            await query.edit_message_text(f"✅ تم حفظ التقرير!\n📍 المحطة: {station}\n🧭 الاتجاه: العفرون → الجزائر\n🕐 الوقت: {report['time']}")
            # Show main menu after 3 seconds
            await asyncio.sleep(3)
            await start(update, context)
            return
            
        # View Reports
        elif data == "view_reports":
            user_data = load_user_data()
            reports = user_data.get("reports", [])
            
            if not reports:
                response = "❌ لا توجد تقارير محفوظة."
                keyboard = [[InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]]
                await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                return
            
            # Group reports by station
            stations_with_reports = {}
            for report in reports:
                station = report["station"]
                if station not in stations_with_reports:
                    stations_with_reports[station] = []
                stations_with_reports[station].append(report)
            
            # Create station buttons
            station_buttons = [
                [InlineKeyboardButton(f"📍 {station} ({len(reports)} تقرير)", callback_data=f"view_station_{station}")]
                for station, reports in stations_with_reports.items()
            ]
            station_buttons.append([InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")])
            await query.edit_message_text("📋 اختر محطة لعرض التقارير:", reply_markup=InlineKeyboardMarkup(station_buttons))
            return
            
        elif data.startswith("view_station_"):
            selected_station = data.split("_", 2)[2]
            user_data = load_user_data()
            reports = user_data.get("reports", [])
            
            # Filter reports by station
            station_reports = [r for r in reports if r["station"] == selected_station]
            
            if not station_reports:
                response = f"❌ لا توجد تقارير للمحطة: {selected_station}"
            else:
                response = f"📋 تقارير المحطة: {selected_station}\n\n"
                for report in sorted(station_reports, key=lambda x: x["timestamp"], reverse=True)[:10]:  # Last 10 reports
                    direction_text = "الجزائر → العفرون" if report["direction"] == DIRECTION_GO else "العفرون → الجزائر"
                    response += f"🧭 {direction_text}\n🕐 {report['time']}\n\n"
            
            keyboard = [
                [InlineKeyboardButton("📋 عرض محطات أخرى", callback_data="view_reports")],
                [InlineKeyboardButton("⬅️ العودة", callback_data="back_to_start")]
            ]
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
                response = f"جميع القطارات القادمة من {station} إلى {destination}:\n\n{train_list}"
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
        logger.error(f"Error in callback handler: {e}")
        try:
            await update.callback_query.edit_message_text("❌ حدث خطأ، يرجى المحاولة مرة أخرى.")
        except:
            pass

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN not set in environment variables.")
        return

    try:
        app = ApplicationBuilder().token(token).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(handle_callback))

        logger.info("✅ Train Schedule Bot is running with Algeria timezone...")
        app.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Bot failed to start: {e}")
        raise

if __name__ == '__main__':
    # Add asyncio import at the top for the sleep function
    import asyncio
    main()
