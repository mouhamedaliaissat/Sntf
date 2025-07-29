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
            return str(result.inserted_id)  # Return the ID as string
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

def delete_report_from_db(report_id):
    """Delete a report by its MongoDB ID"""
    logger.info(f"🗑️ Attempting to delete report with ID: {report_id}")
    try:
        if reports_collection is not None:
            from bson import ObjectId
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
        data = query.data
        
        # Handle delete report request
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
            # Delete the report
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
            
        # Handle delete report cancellation
        elif data.startswith("cancel_delete_"):
            report_id = data.split("_", 2)[2]
            # Show the report details again
            if not MONGO_AVAILABLE or reports_collection is None:
                await query.edit_message_text("❌ قاعدة البيانات غير متوفرة.")
                return
                
            try:
                from bson import ObjectId
                report = reports_collection.find_one({"_id": ObjectId(report_id)})
                if report:
                    direction_text = "الجزائر الى العفرون" if report["direction"] == DIRECTION_GO else "العفرون الى الجزائر"
                    response = f"📋 تفاصيل التقرير:\n"
                    response += f"📍 المحطة: {report['station']}\n"
                    response += f"🧭 الاتجاه: {direction_text}\n"
                    response += f"🕐 الوقت: {report['time']}\n\n"
                    
                    # Add delete button
                    keyboard = [
                        [InlineKeyboardButton("🗑️ حذف التقرير", callback_data=f"delete_report_{report_id}")],
                        [InlineKeyboardButton("⬅️ العودة", callback_data="view_reports")]
                    ]
                    await query.edit_message_text(response, reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    await query.edit_message_text("❌ التقرير غير موجود.")
            except Exception as e:
                logger.error(f"❌ Error retrieving report: {e}")
                await query.edit_message_text("❌ حدث خطأ أثناء استرجاع التقرير.")
            return
            
        # Rest of your existing code...
