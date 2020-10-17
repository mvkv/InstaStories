from Instastories import start_scrape
from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import shutil
import settings
import logging
from thread_runner import ThreadRunner

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

SKIP_EXTENSIONS = (".json", ".txt")

settings.setup_logger()
logger = logging.getLogger(__name__)
user_settings = settings.get()

scraper_runner = ThreadRunner(start_scrape, user_settings["loop_delay_seconds"], user_settings["loop_variation_percentage"])

################### UTIL FUNCTIONS ###################

def get_log_file_list():
    scraping_logs_path = settings.get('scraping_log_file_path')
    if not os.path.exists(scraping_logs_path):
        return []
    with open(scraping_logs_path, "r+") as o:
        logs = [log_lines for log_lines in o.readlines()]
        return list(reversed(logs))

def get_folders(path):
    rendered_folders = []  # List of {type: 'folder', name: Y}
    if not os.path.exists(path): return []
    for folder in os.listdir(path):
        if folder.endswith(SKIP_EXTENSIONS): continue
        rendered_folders.append({'type': 'folder',
                                 'name': f"{folder}"})
    return rendered_folders

def get_media_files(path):
    to_render_media = []
    for media in os.listdir(path):
        if media.endswith(SKIP_EXTENSIONS): continue
        to_render_media.append({'type': 'media', 'name': media, 'is_img': media.endswith(".jpg")})
    return to_render_media

def get_stats_from_log_line(log_lines):
    _, users_count, img_count, video_count = log_lines[-1].split(" - ")
    count_u, count_i, count_v = [int(val.strip().split(" ")[0]) for val in [users_count, img_count, video_count]]
    return count_u, count_i, count_v

def get_disk_usage():
    hdd_usage = shutil.disk_usage("/")
    total_space, used_space, free_space = map(lambda bytes: bytes // (2**30), hdd_usage)
    return f"Used space: {used_space}/{total_space} GiB - Free space: {free_space} GiB"

def get_system_logs():
    log_file_path = settings.get('system_log_file_path')
    if not os.path.exists(log_file_path): return []
    with open(log_file_path, 'r+') as log_file:
        return [log for log in log_file.readlines()]

################### ROUTES ###################

@app.route("/", methods=['GET', 'POST'], defaults={"loop_mode": False, "media_mode": "all", "ids_source": "all"})
def index(loop_mode, media_mode, ids_source):
    logger.info(f"{request.method} request to /index")
    is_user_logged_in = settings.has_setting("session_id")
    user_settings = settings.get()
    if request.method == "POST" and is_user_logged_in:
        user_limit = int(request.form["user_limit"]) if request.form["user_limit"].isdecimal() else -1
        media_mode, ids_source, loop_mode, status_button = request.form["mode_dropdown"], request.form["ids_dropdown"], request.form["loop_dropdown"], request.form["controlBtn"]
        scraper_runner_args = {"scrape_settings": user_settings,
                               "user_limit": user_limit,
                               "media_mode": media_mode,
                               "ids_source": ids_source}
        if status_button == "start":
            loop_mode = loop_mode == "True"
            scraper_runner.updateFuncArg(**scraper_runner_args).startFunction(keep_running=loop_mode)
        elif status_button == "stop": scraper_runner.stopFunction()
        elif status_button == "update": scraper_runner.updateFuncArg(**scraper_runner_args)
    logged_in_error = request.method == "POST" and not is_user_logged_in
    log_lines = get_log_file_list()

    # Retrieving scraping mode args from thread
    if scraper_runner.args:
        loop_mode = not scraper_runner.shutting_down
        media_mode = scraper_runner.args['media_mode']
        ids_source = scraper_runner.args['ids_source']
    return render_template('index.html',
                           log_lines=log_lines,
                           disclaimer={"logged_in_error": logged_in_error},
                           output=scraper_runner.getOutput(),
                           checkbox={"loop_mode": loop_mode, "media_mode": media_mode, "ids_source": ids_source},
                           status=scraper_runner.getStatus())

@app.route("/settings/", methods=['GET', 'POST'])
def settings_page():
    logger.info(f"{request.method} request to /settings/")
    return render_template("settings.html")

@app.route("/gallery/", methods=['GET'], defaults={"text": ''})
@app.route("/gallery/<path:text>", methods=['GET'])
def gallery(text):
    logger.info(f"GET request to /gallery/")
    return render_template("gallery.html", title=text if text else "Gallery")

@app.route("/logs/", methods=['GET'])
def logs():
    return render_template('logs.html', logs=get_system_logs())

################### API ROUTES ###################

@app.route("/api/gallery/", methods=['GET'], defaults={"username": None, "date": None})
@app.route("/api/gallery/<username>/", methods=['GET'], defaults={"date": None})
@app.route("/api/gallery/<username>/<date>/", methods=['GET'])
def gallery_api(username, date):
    logger.info(f"API/{request.method} request to /gallery/{username if username else ''}{'/' + date if date else ''}")
    folder_path = settings.get("folder_path")
    # From most to least specific
    if date:
        date_path = os.path.join(os.path.join(folder_path, username), date)
        to_render_items = get_media_files(date_path)
    elif username:
        user_path = os.path.join(folder_path, username)
        to_render_items = get_folders(user_path)
    else:
        to_render_items = get_folders(folder_path)
    return jsonify({'items': to_render_items})

@app.route("/api/gallery/", methods=['DELETE'])
def delete_media():
    folder_path = settings.get("folder_path")
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path)
        logger.info(f"Deleted {folder_path} folder")
    return jsonify(success=True)

@app.route("/api/settings/", methods=['GET', 'POST'])
def get_settings_api():
    logger.info(f"API/{request.method} request to /settings/")
    if request.method == 'GET':
        return jsonify(settings.get())
    elif request.method == 'POST':
        user_settings = settings.get()
        res = request.get_json()
        user_settings.update(res)
        settings.update_settings_file(user_settings)
        loop_args = {"loop_delay_seconds": int(user_settings["loop_delay_seconds"]),
                     "loop_variation_percentage": int(user_settings["loop_variation_percentage"])}
        scraper_runner.updateDelay(**loop_args)
        return user_settings

@app.route('/api/settings/logout/', methods=["GET"])
def logout():
    logger.info(f"API/{request.method} request to /settings/logout/")
    settings.clear_setting("session_id")
    logger.info("The user has logged out")
    return jsonify(success=True)

################### SERVE MEDIA ###########

@app.route("/gallery/<username>/<date>/<filename>", methods=['GET'])
def serve_media(username, date, filename):
    folder_path = settings.get("folder_path")
    media_folder = os.path.join(os.path.join(folder_path, username), date)
    return send_from_directory(media_folder, filename)

################### RUN ###################


if __name__ == "__main__":
    app.run(debug=True, port=80, host='0.0.0.0')
