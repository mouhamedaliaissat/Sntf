import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from schedules import go_schedule, return_schedule

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DIRECTION_GO = "go"
DIRECTION_RETURN = "return"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚆 الجزائر → العفرون", callback_data="direction_go")],
        [InlineKeyboardButton("🚆 العفرون → الجزائر", callback_data="direction_return")]
    ]
    if update.message:
        await update.message.reply_text("👋 مرحبًا بك! اختر اتجاه القطار:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text("👋 مرحبًا بك! اختر اتجاه القطار:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()

        data = query.data
        
        if data == "direction_go":
            context.user_data["direction"] = DIRECTION_GO
            stations = list(go_schedule.keys())
            # Show station buttons with back button
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
            # Show station buttons with back button
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

            now = datetime.now().time()
            
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
            now = datetime.now().time()
            
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
                # Add button to show all trains
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
    """Main function to run the bot"""
    # Get bot token from environment variables
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("❌ BOT_TOKEN not set in environment variables.")
        return

    try:
        # Build and run bot
        app = ApplicationBuilder().token(token).build()

        # Add handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(handle_callback))

        logger.info("✅ Train Schedule Bot is running on Railway...")
        app.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Bot failed to start: {e}")
        raise

if __name__ == '__main__':
    main()
