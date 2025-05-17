import sys
import os
from pathlib import Path
import tempfile

sys.path.append(str(Path(__file__).parent.parent))

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from werkzeug.utils import secure_filename
from pydub import AudioSegment
from pydub.effects import speedup

app = Flask(__name__)
app.secret_key = "your_secret_key_here"

main_song = None
# Create upload folder if it doesn't exist
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'flac', 'm4a'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
def index():
    return "Hello, World!"
  
@app.route('/set_main_song', methods=['POST'])
def set_main_song():
    global main_song
    data = request.json
    if data and 'filename' in data:
        main_song = data['filename']
        return jsonify({'success': True, 'main_song': main_song})
    return jsonify({'success': False, 'error': 'Invalid request'}), 400
  
@app.route('/upload', methods=['GET', 'POST'])
def upload_audio():
    audio_files = []
    
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'audio_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
            
        file = request.files['audio_file']
        
        # If user does not select file, browser may submit an empty file
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
            # Get other form data
            title = request.form.get('title', filename)
            description = request.form.get('description', '')
            
            flash('File successfully uploaded', 'success')
            # In a real app, you would save this information to a database
            
        else:
            flash('File type not allowed', 'error')
            
    # Get list of uploaded files (in a real app, this would come from a database)
    # This is a simplified example - you would need to modify this for a real application
    try:
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if allowed_file(filename):
                audio_files.append({
                    'filename': filename,
                    'title': filename,
                    'description': '',
                    'is_main': filename == main_song  # Add this property
                })
    except:
        pass
    
    return render_template('audio_upload.html', audio_files=audio_files)

@app.route('/delete_track', methods=['POST'])
def delete_track():
    global main_song
    data = request.json
    
    if not data or 'filename' not in data:
        return jsonify({'success': False, 'error': 'Invalid request'}), 400
    
    filename = data['filename']
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    # Check if file exists
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': 'File not found'}), 404
    
    try:
        # Delete the file
        os.remove(file_path)
        
        # If we deleted the main song, reset the main_song variable
        if main_song == filename:
            main_song = None
            
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/sync_to_main', methods=['POST'])
def sync_to_main():
    global main_song
    data = request.json
    
    if not data or 'filename' not in data or main_song is None:
        return jsonify({'success': False, 'error': 'Missing filename or no main song selected'}), 400
    
    try:
        # Get the files
        main_file_path = os.path.join(app.config['UPLOAD_FOLDER'], main_song)
        track_file_path = os.path.join(app.config['UPLOAD_FOLDER'], data['filename'])
        
        # Load audio files
        main_audio = AudioSegment.from_file(main_file_path)
        track_audio = AudioSegment.from_file(track_file_path)
        
        # Match durations by adjusting speed of the track
        main_duration = len(main_audio)
        track_duration = len(track_audio)
        
        # Calculate the speed factor
        speed_factor = main_duration / track_duration
        
        # Only adjust if the difference is significant
        if abs(1 - speed_factor) > 0.01:
            if speed_factor > 1:
                # Speed up the track
                adjusted_track = speedup(track_audio, speed_factor)
            else:
                # Slow down the track (since speedup can only speed up, we'll use the raw method)
                adjusted_track = track_audio._spawn(track_audio.raw_data, 
                                                 overrides={
                                                     "frame_rate": int(track_audio.frame_rate * speed_factor)
                                                 })
                adjusted_track = adjusted_track.set_frame_rate(track_audio.frame_rate)
                
            # Save the adjusted track with a new filename
            filename_parts = os.path.splitext(data['filename'])
            new_filename = f"{filename_parts[0]}_synced{filename_parts[1]}"
            new_file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            
            # Export the file
            adjusted_track.export(new_file_path, format=filename_parts[1][1:])
            
            return jsonify({
                'success': True, 
                'new_filename': new_filename,
                'message': f"Track synced to main track. Speed adjusted by factor: {speed_factor:.2f}"
            })
        else:
            return jsonify({
                'success': True, 
                'message': "Tracks are already synchronized (duration difference less than 1%)"
            })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/adjust_pitch', methods=['POST'])
def adjust_pitch():
    data = request.json
    
    if not data or 'filename' not in data or 'semitones' not in data:
        return jsonify({'success': False, 'error': 'Missing filename or semitones parameter'}), 400
    
    try:
        # Get the file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], data['filename'])
        
        # Load audio file
        audio = AudioSegment.from_file(file_path)
        
        # Get semitones adjustment
        semitones = float(data['semitones'])
        
        # Calculate pitch shift factor (each semitone is 2^(1/12))
        pitch_factor = 2 ** (semitones / 12)
        
        # Adjust pitch by changing the playback speed and then restoring the tempo
        # (simple approach using pydub)
        adjusted_audio = audio._spawn(audio.raw_data, 
                                    overrides={
                                        "frame_rate": int(audio.frame_rate * pitch_factor)
                                    })
        adjusted_audio = adjusted_audio.set_frame_rate(audio.frame_rate)
        
        # Save the adjusted track with a new filename
        filename_parts = os.path.splitext(data['filename'])
        new_filename = f"{filename_parts[0]}_pitch{semitones}{filename_parts[1]}"
        new_file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
        
        # Export the file
        adjusted_audio.export(new_file_path, format=filename_parts[1][1:])
        
        return jsonify({
            'success': True, 
            'new_filename': new_filename,
            'message': f"Pitch adjusted by {semitones} semitones"
        })
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500