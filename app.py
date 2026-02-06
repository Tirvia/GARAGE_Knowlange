import os
import re
import markdown
from flask import Flask, render_template, request, send_from_directory, jsonify
from pathlib import Path
import logging
from datetime import datetime
import html

# Настройка логирования для Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Конфигурация для Railway
app.config['DATA_FOLDER'] = os.environ.get('DATA_FOLDER', 'data')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['TITLE_PATTERN'] = re.compile(r'#\s+(.+)$', re.MULTILINE)

# Для Railway важно использовать правильный путь к статическим файлам
if not os.path.exists(app.config['DATA_FOLDER']):
    os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)
    logger.info(f"Created data folder: {app.config['DATA_FOLDER']}")

def get_instruction_path(instruction_id=None):
    """Получает путь к папке инструкции"""
    if instruction_id:
        return os.path.join(app.config['DATA_FOLDER'], instruction_id)
    return app.config['DATA_FOLDER']

def extract_instruction_info(folder_path):
    """Извлекает информацию об инструкции из папки"""
    try:
        info = {
            'id': os.path.basename(folder_path),
            'title': os.path.basename(folder_path),
            'content': '',
            'images': [],
            'modified': os.path.getmtime(folder_path) if os.path.exists(folder_path) else 0
        }
        
        # Проверяем существование папки
        if not os.path.exists(folder_path):
            logger.warning(f"Folder does not exist: {folder_path}")
            return info
        
        # Ищем markdown файл
        for file in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file)
            if file.endswith('.md'):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # Извлекаем заголовок из содержимого
                        match = app.config['TITLE_PATTERN'].search(content)
                        if match:
                            info['title'] = match.group(1)
                        info['content'] = content
                except Exception as e:
                    logger.error(f"Error reading MD file {file_path}: {e}")
                    info['content'] = f"Ошибка чтения файла: {str(e)}"
            elif file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                info['images'].append(file)
        
        return info
    except Exception as e:
        logger.error(f"Error extracting instruction info from {folder_path}: {e}")
        return {
            'id': os.path.basename(folder_path),
            'title': f"Ошибка: {str(e)}",
            'content': '',
            'images': [],
            'modified': 0
        }

def scan_instructions():
    """Сканирует все инструкции в папке data"""
    instructions = []
    data_folder = get_instruction_path()
    
    if not os.path.exists(data_folder):
        logger.warning(f"Data folder does not exist: {data_folder}")
        return instructions
    
    try:
        for folder in os.listdir(data_folder):
            folder_path = os.path.join(data_folder, folder)
            if os.path.isdir(folder_path):
                info = extract_instruction_info(folder_path)
                if info['content']:  # Только если есть содержимое
                    instructions.append(info)
        
        # Сортируем по дате изменения (новые сначала)
        instructions.sort(key=lambda x: x['modified'], reverse=True)
        
        logger.info(f"Scanned {len(instructions)} instructions")
        return instructions
    except Exception as e:
        logger.error(f"Error scanning instructions: {e}")
        return []

def convert_buildin_links(content, instructions_dict):
    """Заменяет ссылки BuildIn на внутренние ссылки"""
    try:
        # Паттерн для поиска ссылок BuildIn
        buildin_pattern = r'https://buildin\.ai/share/([a-f0-9-]+)'
        
        def replace_link(match):
            buildin_id = match.group(1)
            # Ищем соответствующую инструкцию по ID
            for instr_id, instr_info in instructions_dict.items():
                if buildin_id in instr_id or buildin_id in instr_info.get('title', ''):
                    return f'/instruction/{instr_id}'
            return match.group(0)  # Если не нашли, оставляем как есть
        
        return re.sub(buildin_pattern, replace_link, content)
    except Exception as e:
        logger.error(f"Error converting BuildIn links: {e}")
        return content

def markdown_to_html(content, instruction_id, instructions_dict):
    """Конвертирует markdown в HTML с поддержкой изображений и заменой ссылок"""
    try:
        # Сначала заменяем ссылки BuildIn
        content = convert_buildin_links(content, instructions_dict)
        
        # Обрабатываем изображения
        def replace_image(match):
            image_url = match.group(2)
            # Если это URL, оставляем как есть
            if image_url.startswith('http'):
                return match.group(0)
            # Иначе делаем локальную ссылку
            return f'![{match.group(1)}](/image/{instruction_id}/{image_url})'
        
        # Заменяем локальные пути к изображениям
        image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        content = re.sub(image_pattern, replace_image, content)
        
        # Конвертируем markdown в HTML с расширениями
        html = markdown.markdown(content, extensions=[
            'extra',  # Таблицы, аббревиатуры и т.д.
            'tables',
            'fenced_code',  # Блоки кода
            'codehilite',  # Подсветка синтаксиса
            'toc'  # Оглавление
        ])
        
        return html
    except Exception as e:
        logger.error(f"Error converting markdown to HTML: {e}")
        return f"<p>Ошибка преобразования содержимого: {str(e)}</p>"

def format_datetime(timestamp):
    """Форматирует timestamp в читаемый вид"""
    if timestamp:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%d.%m.%Y %H:%M")
    return "Неизвестно"

def search_in_instructions(instructions, query, search_type='title', search_mode='any'):
    """Поиск в инструкциях по различным критериям"""
    if not query:
        return instructions
    
    query = query.lower().strip()
    results = []
    
    for instr in instructions:
        content_lower = instr['content'].lower()
        title_lower = instr['title'].lower()
        
        if search_type == 'title':
            # Поиск только в заголовке
            if query in title_lower:
                instr['preview'] = f"<strong>Название:</strong> {instr['title']}"
                results.append(instr)
        
        elif search_type == 'content':
            # Поиск в содержимом
            if query in content_lower:
                # Найдем контекст вокруг найденного текста
                content = instr['content']
                query_pos = content_lower.find(query)
                
                if query_pos >= 0:
                    start = max(0, query_pos - 100)
                    end = min(len(content), query_pos + len(query) + 100)
                    preview = content[start:end]
                    
                    # Выделим найденный текст
                    preview_lower = preview.lower()
                    query_pos_in_preview = preview_lower.find(query)
                    
                    if query_pos_in_preview >= 0:
                        before = preview[:query_pos_in_preview]
                        found = preview[query_pos_in_preview:query_pos_in_preview + len(query)]
                        after = preview[query_pos_in_preview + len(query):]
                        preview = f"{before}<mark>{found}</mark>{after}"
                    
                    instr['preview'] = f"<strong>Название:</strong> {instr['title']}<br><strong>Контекст:</strong> ...{preview}..."
                results.append(instr)
        
        elif search_type == 'advanced':
            # Расширенный поиск
            if search_mode == 'exact':
                # Точная фраза
                if query in content_lower or query in title_lower:
                    results.append(instr)
            elif search_mode == 'all':
                # Все слова
                words = query.split()
                content_search = all(word in content_lower for word in words)
                title_search = all(word in title_lower for word in words)
                if content_search or title_search:
                    results.append(instr)
            else:  # any - любое слово
                words = query.split()
                content_search = any(word in content_lower for word in words)
                title_search = any(word in title_lower for word in words)
                if content_search or title_search:
                    results.append(instr)
    
    return results

@app.template_filter('datetime')
def datetime_filter(timestamp):
    """Фильтр для форматирования даты в шаблоне"""
    return format_datetime(timestamp)

@app.template_filter('striptags')
def striptags_filter(text):
    """Удаляет HTML теги из текста"""
    return html.escape(re.sub(r'<[^>]*>', '', text))

@app.route('/')
def index():
    """Главная страница с поиском"""
    try:
        query = request.args.get('q', '')
        search_type = request.args.get('search_type', 'title')
        search_mode = request.args.get('search_mode', 'any')
        sort = request.args.get('sort', 'relevance')
        
        instructions = scan_instructions()
        
        # Определяем отображаемое название типа поиска
        search_type_display = {
            'title': 'по названию',
            'content': 'по содержанию',
            'advanced': 'расширенный'
        }.get(search_type, 'по названию')
        
        if query:
            instructions = search_in_instructions(
                instructions, 
                query, 
                search_type, 
                search_mode
            )
            
            # Сортировка результатов
            if sort == 'date_new':
                instructions.sort(key=lambda x: x['modified'], reverse=True)
            elif sort == 'date_old':
                instructions.sort(key=lambda x: x['modified'])
            elif sort == 'title':
                instructions.sort(key=lambda x: x['title'].lower())
            # По умолчанию остается сортировка по релевантности
        
        return render_template('index.html', 
                             instructions=instructions, 
                             query=query,
                             search_type=search_type,
                             search_type_display=search_type_display,
                             total_instructions=len(scan_instructions()))
    except Exception as e:
        logger.error(f"Error in index route: {e}")
        return render_template('error.html', error=str(e)), 500

@app.route('/instruction/<instruction_id>')
def show_instruction(instruction_id):
    """Показывает конкретную инструкцию"""
    try:
        instructions = scan_instructions()
        instructions_dict = {instr['id']: instr for instr in instructions}
        
        if instruction_id not in instructions_dict:
            logger.warning(f"Instruction not found: {instruction_id}")
            return render_template('404.html', instruction_id=instruction_id), 404
        
        instruction = instructions_dict[instruction_id]
        
        # Конвертируем markdown в HTML
        html_content = markdown_to_html(
            instruction['content'], 
            instruction_id, 
            instructions_dict
        )
        
        # Получаем связанные инструкции
        related_instructions = []
        for instr_id, instr_info in instructions_dict.items():
            if instr_id != instruction_id:
                # Проверяем, ссылается ли текущая инструкция на другую
                if instr_id in instruction['content'] or instr_info['title'] in instruction['content']:
                    related_instructions.append(instr_info)
        
        return render_template(
            'instruction.html',
            title=instruction['title'],
            content=html_content,
            instruction_id=instruction_id,
            related=related_instructions,
            total_instructions=len(instructions),
            modified=instruction['modified']
        )
    except Exception as e:
        logger.error(f"Error showing instruction {instruction_id}: {e}")
        return render_template('error.html', error=str(e)), 500

@app.route('/image/<instruction_id>/<filename>')
def serve_image(instruction_id, filename):
    """Отдает изображения из папки инструкции"""
    try:
        folder_path = get_instruction_path(instruction_id)
        if not os.path.exists(folder_path):
            logger.warning(f"Instruction folder not found: {folder_path}")
            return "Изображение не найдено", 404
        
        image_path = os.path.join(folder_path, filename)
        if not os.path.exists(image_path):
            logger.warning(f"Image not found: {image_path}")
            return "Изображение не найдено", 404
        
        return send_from_directory(folder_path, filename)
    except Exception as e:
        logger.error(f"Error serving image {instruction_id}/{filename}: {e}")
        return "Ошибка при загрузке изображения", 500

@app.route('/api/search')
def api_search():
    """API для поиска (для AJAX)"""
    try:
        query = request.args.get('q', '')
        search_type = request.args.get('type', 'title')
        
        if len(query) < 2:
            return jsonify({'results': []})
        
        instructions = scan_instructions()
        
        results = []
        query_lower = query.lower()
        
        for instr in instructions:
            match = False
            
            if search_type == 'title':
                match = query_lower in instr['title'].lower()
            elif search_type == 'content':
                match = query_lower in instr['content'].lower()
            
            if match:
                # Создаем превью
                if search_type == 'title':
                    preview = f"Найдено в названии: {instr['title']}"
                else:
                    # Находим позицию в контенте для превью
                    content_lower = instr['content'].lower()
                    pos = content_lower.find(query_lower)
                    if pos >= 0:
                        start = max(0, pos - 50)
                        end = min(len(instr['content']), pos + len(query) + 50)
                        context = instr['content'][start:end]
                        preview = f"...{context}..."
                    else:
                        preview = instr['content'][:150] + '...'
                
                results.append({
                    'id': instr['id'],
                    'title': instr['title'],
                    'preview': preview
                })
        
        return jsonify({'results': results[:10]})  # Ограничиваем 10 результатами
    except Exception as e:
        logger.error(f"Error in API search: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/instructions')
def api_instructions():
    """API для получения списка всех инструкций"""
    try:
        instructions = scan_instructions()
        return jsonify({
            'count': len(instructions),
            'instructions': [
                {
                    'id': instr['id'],
                    'title': instr['title'],
                    'image_count': len(instr['images']),
                    'modified': instr['modified']
                } for instr in instructions
            ]
        })
    except Exception as e:
        logger.error(f"Error in API instructions: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check для Railway"""
    return jsonify({
        'status': 'healthy',
        'service': 'База знаний GARAGE',
        'instruction_count': len(scan_instructions()),
        'search_types': ['title', 'content', 'advanced']
    })

@app.errorhandler(404)
def page_not_found(e):
    """Обработчик 404 ошибок"""
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Обработчик 500 ошибок"""
    return render_template('error.html', error=str(e)), 500

# Для Railway важно указать этот блок
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', 'False') == 'True')