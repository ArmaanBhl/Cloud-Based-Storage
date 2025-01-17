from flask import Flask, jsonify, render_template, redirect,session, url_for, request, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from psutil import users
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime
from flask_migrate import Migrate


# Initialize Flask app
app = Flask(__name__) 

# Configuration
UPLOAD_FOLDER = 'uploads'
TRASH_FOLDER = 'trash'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['TRASH_FOLDER'] = TRASH_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TRASH_FOLDER, exist_ok=True)  # Ensure the trash folder exists

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 10240 * 10240  # Max file size (16 MB)
app.secret_key = 'your_secret_key'
app.config['ENV'] = 'production'
app.config['DEBUG'] = False

# Initialize the database
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    files = db.relationship('File', backref='owner', lazy=True)
    max_storage_limit = db.Column(db.Integer, default=10240)


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(150), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    size = db.Column(db.Integer, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    starred = db.Column(db.Boolean, default=False)

# Routes
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('profile', user_id=session['user_id']))  # Redirect to profile if logged in
    return redirect(url_for('signup'))  # Redirect to signup page if not logged in


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("Username already exists", "error")
            return redirect(url_for('signup'))
        
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash("Account created successfully!", "success")
        return redirect(url_for('login'))
    
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash(f"Welcome, {user.username}!", "success")
            return redirect(url_for('profile', user_id=user.id))
        
        flash("Invalid credentials", "error")
    
    return render_template('login.html')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}  # Define allowed file types

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/profile/<int:user_id>', methods=['GET', 'POST'])
def profile(user_id):
    # Ensure the user is logged in and accessing their profile
    if 'user_id' not in session or session['user_id'] != user_id:
        flash("Please log in to access your profile.", "warning")
        return redirect(url_for('login'))

    # Retrieve the user or handle the case where the user doesn't exist
    user = User.query.get(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for('login'))
    
    # Get the filter option from the query string (default to 'name_asc')
    filter_by = request.args.get('filter_by', 'name_asc')

    # Get the search query, if any
    query = request.args.get('query', '').strip()

    # Initialize files with a default query to avoid UnboundLocalError
    files = File.query.filter_by(user_id=user_id, deleted_at=None)

    # Filter logic based on the selected filter option
    if filter_by == 'name_desc':
        files = files.order_by(File.filename.desc())
    elif filter_by == 'size_asc':
        files = files.order_by(File.size.asc())
    elif filter_by == 'size_desc':
        files = files.order_by(File.size.desc())
    elif filter_by == 'date_asc':
        files = files.order_by(File.timestamp.asc())
    elif filter_by == 'date_desc':
        files = files.order_by(File.timestamp.desc())

    # Apply search query filter if any
    if query:
        files = files.filter(File.filename.ilike(f"%{query}%"))

    # Execute the query to retrieve the files
    files = files.all()

    # Check if any files are starred and include them in the result set
    starred_files = File.query.filter_by(user_id=user_id, starred=True).all()

    # Handle file upload
    if request.method == 'POST' and 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            file_size = os.path.getsize(file_path)

            # Calculate total used storage
            total_used_storage = sum(f.size for f in files)

            # Check for storage limit
            if (total_used_storage + file_size) / (1024 * 1024) > user.max_storage_limit:
                flash("Cannot upload file. Storage limit exceeded.", "error")
                return redirect(url_for('profile', user_id=user.id))

            # Check for existing file and update if necessary
            existing_file = File.query.filter_by(user_id=user_id, filename=filename).first()
            if existing_file:
                existing_file.timestamp = datetime.utcnow()
                existing_file.size = file_size
                db.session.commit()
                flash("File updated successfully!", "info")
            else:
                # Add the new file to the database
                new_file = File(filename=filename, user_id=user_id, size=file_size)
                db.session.add(new_file)
                db.session.commit()
                flash("File uploaded successfully!", "success")
        else:
            flash("Invalid file or file type.", "error")
            return redirect(url_for('profile', user_id=user.id))

    # Storage calculations
    max_storage = user.max_storage_limit or 10000  # Default to 10 GB if not set
    used_storage = sum(f.size for f in files) / (1024 * 1024)  # Convert bytes to MB
    used_storage = round(used_storage, 2)

    return render_template(
        'profile.html',
        user=user,
        files=files,
        starred_files=starred_files,
        query=query,
        used_storage=used_storage,
        max_storage=max_storage,
        filter_by=filter_by
    )



@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        # Step 1: Check if a username is provided
        username = request.form.get('username', None)
        new_password = request.form.get('new_password', None)
        
        # Step 2: Validate the username
        user = User.query.filter_by(username=username).first()
        
        if not user:
            flash("Username not found.", "error")
            return render_template('forgot_password.html', is_profile_page=False)

        # Step 3: Handle new password submission
        if new_password:
            hashed_password = generate_password_hash(new_password)
            user.password = hashed_password
            db.session.commit()
            flash("Password reset successfully! You can now log in.", "success")
            return redirect(url_for('login'))
        
        # Step 4: Show the reset password form
        return render_template(
            'forgot_password.html',
            is_profile_page=False,
            username=username,
            show_reset_form=True
        )
    
    # Default GET request
    return render_template('forgot_password.html', is_profile_page=False)



@app.route('/reset_password', methods=['POST'])
def reset_password():
    data = request.form
    username = data.get('username')
    new_password = data.get('new_password')

    if username in users:
        users[username] = new_password
        return "Password reset successfully!"
    return "Error resetting password!", 400



@app.route('/uploads/<filename>')
def download_file(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(file_path):
        flash(f"File {filename} not found", "error")
        return redirect(url_for('profile', user_id=session.get('user_id')))
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/delete_file/<int:file_id>', methods=['POST'])
def delete_file(file_id):
    if 'user_id' not in session:
        flash('You must be logged in to delete files.', 'error')
        return redirect(url_for('login'))  # Redirect to login page if user is not authenticated

    file = File.query.get(file_id)
    if file:
        file.deleted_at = datetime.now()  # Track the deletion timestamp
        db.session.commit()

        # Move the file to the trash folder
        source_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        if os.path.exists(source_path):
            trash_path = os.path.join('trash', file.filename)
            os.rename(source_path, trash_path)  # Move file to trash
            flash("File moved to trash.", "success")
        else:
            flash(f"Error: {file.filename} not found.", "error")

        return redirect(url_for('profile', user_id=session['user_id']))
    else:
        flash('File not found.', 'error')
        return redirect(url_for('profile', user_id=session['user_id']))

@app.route('/trash')
def trash():
    files = File.query.filter(File.deleted_at != None).all()  # Fetch deleted files
    return render_template('trash.html', files=files)


@app.route('/recover_file/<int:file_id>', methods=['POST'])
def recover_file(file_id):
    if 'user_id' not in session:
        flash('You must be logged in to recover files.', 'error')
        return redirect(url_for('login'))  # Redirect to login page if user is not authenticated

    file = File.query.get(file_id)
    if file and file.deleted_at:
        trash_path = os.path.join('trash', file.filename)
        original_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)

        if os.path.exists(trash_path):
            # Check if the file already exists in the original location
            if os.path.exists(original_path):
                # Rename the file to avoid overwriting
                base, ext = os.path.splitext(file.filename)
                new_filename = f"{base}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
                original_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)

                flash(f"A file with the same name already exists. Renaming the recovered file to {new_filename}.", "info")

            # Move the file from trash to the original location
            os.rename(trash_path, original_path)  # Recover the file
            file.deleted_at = None  # Clear the deleted timestamp
            db.session.commit()
            flash("File recovered successfully.", "success")
        else:
            flash("File not found in trash.", "error")

        return redirect(url_for('trash'))
    else:
        flash('File not found or already recovered.', 'error')
        return redirect(url_for('trash'))


@app.route('/delete_permanently/<int:file_id>', methods=['POST'])
def delete_permanently(file_id):
    if 'user_id' not in session:
        flash('You must be logged in to delete files permanently.', 'error')
        return redirect(url_for('login'))

    file = File.query.get(file_id)
    if file:
        trash_path = os.path.join(app.config['TRASH_FOLDER'], file.filename)

        # Remove the file from the file system if it exists
        if os.path.exists(trash_path):
            os.remove(trash_path)
            flash("File permanently deleted.", "success")
        else:
            flash("File not found in trash.", "error")

        # Remove the file record from the database
        db.session.delete(file)
        db.session.commit()

        return redirect(url_for('trash'))
    else:
        flash('File not found.', 'error')
        return redirect(url_for('trash'))


@app.route('/rename_file', methods=['POST'])
def rename_file():
    if 'user_id' not in session:
        flash('You must be logged in to rename files.', 'error')
        return redirect(url_for('login'))

    file_id = request.form['file_id']
    new_filename = request.form['new_filename']

    # Fetch the file from the database
    file = File.query.get(file_id)
    if file:
        # Ensure new filename is unique for the user
        existing_file = File.query.filter_by(user_id=session['user_id'], filename=new_filename).first()
        if existing_file:
            flash('A file with this name already exists.', 'error')
            return redirect(url_for('profile', user_id=session['user_id']))

        # Rename the file on the filesystem
        old_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        new_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
        if os.path.exists(old_path):
            os.rename(old_path, new_path)

        # Update the filename in the database
        file.filename = new_filename
        db.session.commit()
        flash('File renamed successfully.', 'success')
    else:
        flash('File not found.', 'error')

    return redirect(url_for('profile', user_id=session['user_id']))

@app.route('/starred', methods=['GET'])
def starred():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.get(user_id)  # Fetch user details

    # Fetch starred files for the logged-in user
    starred_files = File.query.filter_by(user_id=user_id, starred=True).all()

    # Get the search query, if any (optional)
    query = request.args.get('query', '').strip()

    # Handle the search functionality
    if query:
        starred_files = [file for file in starred_files if query.lower() in file.filename.lower()]

    # Calculate storage (if necessary, you can modify this part)
    used_storage = sum(f.size for f in starred_files) / (1024 * 1024)  # Convert bytes to MB
    used_storage = round(used_storage, 2)

    return render_template(
        'starred.html',  # Using profile template for consistency
        user=user,
        files=starred_files,
        query=query,
        used_storage=used_storage,
        max_storage=user.max_storage_limit
    )


@app.route('/toggle_starred/<int:file_id>', methods=['POST'])
def toggle_starred(file_id):
    # Ensure the user is logged in and has permission to modify the file
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    user_id = session['user_id']
    
    # Retrieve the file from the database
    file = File.query.filter_by(id=file_id, user_id=user_id).first()

    if not file:
        return jsonify({'success': False, 'message': 'File not found'}), 404

    # Toggle the starred status
    file.starred = not file.starred
    db.session.commit()

    return jsonify({'success': True, 'starred': file.starred})


@app.route('/filter_files')
def filter_files():
    filter_type = request.args.get('filter_type')

    # Validate filter type
    if filter_type not in ['size', 'alphabet', 'date']:
        return jsonify({'success': False, 'message': 'Invalid filter type'}), 400
    
    # Retrieve all files for the logged-in user
    user_id = session.get('user_id')
    files = File.query.filter_by(user_id=user_id, deleted_at=None).all()

    # Sort the files based on the selected filter type
    if filter_type == 'size':
        files = sorted(files, key=lambda f: f.size)  # Sort by file size
    elif filter_type == 'alphabet':
        files = sorted(files, key=lambda f: f.filename.lower())  # Sort alphabetically
    elif filter_type == 'date':
        files = sorted(files, key=lambda f: f.timestamp, reverse=True)  # Sort by date uploaded

    # Return the filtered files
    file_data = [{
        'filename': file.filename,
        'size': file.size,
        'timestamp': file.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    } for file in files]

    return jsonify({'success': True, 'files': file_data})


@app.route('/logout')
def logout():
    session.clear()  # Clear session
    return redirect(url_for('login'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Ensure tables are created
    app.run(debug=True)
