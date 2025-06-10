# ================================================================================
#                               PST File Search Tool
# ================================================================================
#
# usage: main.py [-h] --output-dir OUTPUT_DIR [--sender SENDER] [--recipient RECIPIENT] [--subject SUBJECT]
#                [--body BODY] [-sent-after SENT_AFTER] [--sent-before SENT_BEFORE] [--received-after RECEIVED_AFTER]
#                [--received-before RECEIVED_BEFORE] [--sent-time SENT_TIME] [--received-time RECEIVED_TIME]
#                pst_file

import os
import argparse
from datetime import datetime, timezone, timedelta
import pypff
import re
import unicodedata
from bs4 import BeautifulSoup
from striprtf.striprtf import rtf_to_text
import zipfile
import io
from bs4 import Comment
from email.header import decode_header

# from email.utils import parseaddr

# Константа для временной зоны GMT+3
GMT3 = timezone(timedelta(hours=3))


def print_header():
    """Выводит заголовок программы"""
    print("\n" + "=" * 80)
    print("PST File Search Tool".center(80))
    print("=" * 80 + "\n")


def decode_mime_string(mime_string):
    """Декодирует MIME-строку с учетом возможных ошибок"""
    if not mime_string or mime_string == "No value":
        return mime_string

    # Если передан список с одним элементом, берем этот элемент
    if isinstance(mime_string, list) and len(mime_string) == 1:
        mime_string = mime_string[0]
    # Если передан список с несколькими элементами, объединяем их через пробел
    elif isinstance(mime_string, list):
        mime_string = ' '.join(str(item) for item in mime_string)


    try:
        decoded_parts = []
        for part, charset in decode_header(mime_string):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(charset or 'utf-8', errors='replace'))
            else:
                decoded_parts.append(str(part))
        return ' '.join(decoded_parts)
    except Exception as e:
        print(f"Error decoding '{mime_string}': {e}")
        return mime_string


def get_header_value(headers, header_name):
    """
    Функция для извлечения значения заголовка по имени.
    Возвращает список строк (даже для одиночных значений).

    Args:
        headers: Список строк заголовков
        header_name: Имя заголовка для поиска (без двоеточия)

    Returns:
        Список найденных значений заголовка (может быть пустым)
    """
    if not headers or not header_name:
        return [""]

    header_name = header_name.rstrip(':')  # Удаляем двоеточие если есть
    header_name_lower = header_name.lower()
    values = []
    current_value = None

    for line in headers:
        # Проверяем начало строки с учетом возможных пробелов
        line_lower = line.strip().lower()
        if line_lower.startswith(header_name_lower + ':'):
            if current_value is not None:
                values.append(current_value)
            current_value = line.split(':', 1)[1].strip() if ':' in line else ""
        elif current_value is not None and (line.startswith(' ') or line.startswith('\t')):
            # Продолжение многострочного заголовка
            current_value += ' ' + line.strip()
        elif current_value is not None:
            # Конец текущего заголовка
            values.append(current_value)
            current_value = None

    if current_value is not None:
        values.append(current_value)

    if not values:
        return [""]

    # Разделяем значения по запятым, но учитываем закавыченные строки
    result = []
    for value in values:
        # Удаляем лишние переносы строк и пробелы
        cleaned_value = ' '.join(value.replace('\r', '').replace('\n', '').split())

        # Декодируем MIME-кодированные части
        decoded_value = decode_mime_string(cleaned_value)

        # Разделяем по запятым, но не внутри кавычек
        parts = re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', decoded_value)

        # Добавляем непустые части в результат
        result.extend([part.strip() for part in parts if part.strip()])

    return result if result else [""]

# def get_header_value(headers, header_name):
#     """
#     Функция для извлечения значения заголовка по имени.
#     Возвращает список строк (даже для одиночных значений).
#     """
#     header_name = header_name.rstrip(':')  # Удаляем двоеточие если есть
#     header_name_lower = header_name.lower()
#     values = []
#     current_value = None
#
#     for line in headers:
#         if line.lower().startswith(header_name_lower + ':'):
#             if current_value is not None:
#                 values.append(current_value)
#             current_value = line.split(':', 1)[1].strip() if ':' in line else ""
#         elif current_value is not None and (line.startswith(' ') or line.startswith('\t')):
#             current_value += ' ' + line.strip()
#         elif current_value is not None:
#             values.append(current_value)
#             current_value = None
#
#     if current_value is not None:
#         values.append(current_value)
#
#     if not values:
#         return ["No value"]
#
#     # Разделяем значения по запятым, но учитываем MIME-кодировки
#     result = []
#     for value in values:
#         cleaned_value = ' '.join(value.replace('\r', '').replace('\n', '').split())
#         print('cleaned_value')
#         print(cleaned_value)
#         # cleaned_value = ' '.join(encoded_text(word) for word in cleaned_value.split())
#         parts = [decode_mime_string(part) for part in re.split(r',\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', cleaned_value)]
#         result.extend([part.strip() for part in parts if part.strip()])
#         print('Result')
#         print(result)
#     return result if result else [""]


def ensure_output_dir(output_dir):
    """Создает каталог для сохранения, если он не существует"""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"[+] Создан каталог для сохранения: {output_dir}")


def sanitize_filename(filename):
    """Очищает строку для использования в имени файла"""
    # print(f'Filename {filename}')
    filename = unicodedata.normalize('NFKD', filename)
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    filename = filename.replace('\n', ' ').replace('\r', ' ')
    filename = filename.strip('. ')
    return filename[:250]


def convert_to_gmt3(dt):
    """Конвертирует datetime в GMT+3"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Если время без временной зоны, считаем что это UTC
        return dt.replace(tzinfo=timezone.utc).astimezone(GMT3)
    return dt.astimezone(GMT3)


def format_datetime_gmt3(dt):
    """Форматирует datetime в строку с указанием GMT+3"""
    if dt is None:
        return "Неизвестно"
    dt_gmt3 = convert_to_gmt3(dt)
    return dt_gmt3.strftime('%Y-%m-%d %H:%M:%S (GMT+3)')


def get_message_body(message):
    """Улучшенное извлечение тела письма с обработкой RTF и нормализацией переносов строк"""

    def normalize_newlines(text):
        """Удаляет множественные переносы строк и лишние пробелы"""
        if not text:
            return text
        # Заменяем последовательности переносов строк на одинарные
        text = re.sub(r'([\r\n]+ ?)+', '\n', text)
        # Удаляем пробелы в начале и конце строк
        text = '\n'.join(line.strip() for line in text.split('\n'))
        return text.strip()

    try:
        # Пытаемся получить plain text тело
        body = getattr(message, 'plain_text_body', None)
        if body:
            if isinstance(body, bytes):
                body = body.decode('utf-8', errors='replace')
            return normalize_newlines(str(body))

        # Пытаемся получить RTF тело
        rtf_body = getattr(message, 'rtf_body', None)
        if rtf_body:
            if isinstance(rtf_body, bytes):
                rtf_body = rtf_body.decode('utf-8', errors='replace')
            if rtf_body:
                return normalize_newlines(rtf_to_text(rtf_body.strip()))

        # Пытаемся получить HTML тело
        html_body = getattr(message, 'html_body', None)
        if html_body:
            # Извлекаем текст из HTML
            soup = BeautifulSoup(html_body, 'html.parser')
            # Удаляем HTML комментарии
            for element in soup.find_all(string=lambda text: isinstance(text, Comment)):
                element.extract()
            plain_text = soup.get_text()
            return normalize_newlines(plain_text)

        return "Тело письма отсутствует"
    except Exception as e:
        print(f"[!] Ошибка извлечения тела письма: {e}")
        return "Не удалось извлечь текст"


def get_folder_path(message):
    """Возвращает путь к папке, содержащей сообщение"""
    try:
        folder = message.parent_folder
        path = []
        while folder:
            path.append(getattr(folder, 'name', 'Unknown Folder'))
            folder = getattr(folder, 'parent_folder', None)
        return " > ".join(reversed(path))
    except Exception as e:
        print(f"[!] Ошибка при получении пути к папке: {e}")
        return "Неизвестная папка"


def check_time_in_range(dt, time_range):
    """Проверяет, попадает ли время в указанный диапазон часов"""
    if not dt:
        return False

    dt_gmt3 = convert_to_gmt3(dt)
    t = dt_gmt3.time()
    start_hour, end_hour = time_range

    if start_hour <= end_hour:
        return start_hour <= t.hour < end_hour
    else:
        return t.hour >= start_hour or t.hour < end_hour


def matches_criteria(sender, subject, body,
                     received_time, sent_time, criteria):
    """Проверяет соответствие сообщения критериям поиска"""
    if criteria.get('sender') and criteria['sender'].lower() not in sender.lower():
        return False

    if criteria.get('subject') and criteria['subject'].lower() not in subject.lower():
        return False

    if criteria.get('body') and criteria['body'].lower() not in body.lower():
        return False

    # Конвертируем временные метки в GMT+3 перед сравнением
    received_time_gmt3 = convert_to_gmt3(received_time) if received_time else None
    sent_time_gmt3 = convert_to_gmt3(sent_time) if sent_time else None

    if criteria.get('received_after') and received_time_gmt3:
        if received_time_gmt3 < convert_to_gmt3(criteria['received_after']):
            return False

    if criteria.get('received_before') and received_time_gmt3:
        if received_time_gmt3 > convert_to_gmt3(criteria['received_before']):
            return False

    if criteria.get('sent_after') and sent_time_gmt3:
        if sent_time_gmt3 < convert_to_gmt3(criteria['sent_after']):
            return False

    if criteria.get('sent_before') and sent_time_gmt3:
        if sent_time_gmt3 > convert_to_gmt3(criteria['sent_before']):
            return False

    if criteria.get('received_time_range') and received_time_gmt3:
        if not check_time_in_range(received_time_gmt3, criteria['received_time_range']):
            return False

    if criteria.get('sent_time_range') and sent_time_gmt3:
        if not check_time_in_range(sent_time_gmt3, criteria['sent_time_range']):
            return False

    return True


def detect_attachment_type(data):
    """Определяет тип вложения по сигнатуре и содержимому"""
    if not data:
        return 'bin'

    # PDF
    if data.startswith(b'%PDF'):
        return 'pdf'

    # RAR (версии 1.5-4.x)
    elif data.startswith(b'Rar!\x1A\x07\x00'):
        return 'rar'

    # RAR5 (версии 5.0+)
    elif data.startswith(b'Rar!\x1A\x07\x01\x00'):
        return 'rar'

    # 7-Zip
    elif data.startswith(b'7z\xBC\xAF\x27\x1C'):
        return '7z'

    # ZIP-based форматы (DOCX, XLSX, ZIP и т.д.)
    elif data.startswith(b'PK\x03\x04'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                if any(name.startswith('word/') for name in names):
                    return 'docx'
                elif any(name.startswith('xl/') for name in names):
                    return 'xlsx'
                elif any(name.startswith('ppt/') for name in names):
                    return 'pptx'
                else:
                    return 'zip'
        except Exception:
            return 'zip'
    else:
        # Попробуем определить по расширению, если данные начинаются с пути/имени файла
        if len(data) > 4:
            # Простая проверка на текстовое начало (возможно, имя файла)
            try:
                first_part = data[:100].decode('ascii', errors='ignore').lower()
                if first_part.endswith('.7z'):
                    return '7z'
                elif first_part.endswith('.rar'):
                    return 'rar'
                elif first_part.endswith('.zip'):
                    return 'zip'
                elif first_part.endswith('.pdf'):
                    return 'pdf'
            except UnicodeDecodeError:
                pass

        return 'bin'


def save_attachments(message, attachments_dir):
    """Сохраняет все вложения из письма с расширением по сигнатуре и уникальным номером"""
    try:
        if not hasattr(message, 'attachments') or message.number_of_attachments == 0:
            return 0

        saved_count = 0
        attachment_id = 1  # Уникальный номер вложения

        for attachment in message.attachments:
            try:
                # Чтение байтов вложения
                data = attachment.read_buffer(attachment.size)

                # Проверка размера вложения
                if len(data) == 0:
                    print(f"    [!] Пропущено вложение (нулевой размер)")
                    continue

                # Определяем тип вложения по сигнатуре
                ext = detect_attachment_type(data)
                if ext == 'bin':
                    print(f"    [!] Пропущено вложение (неизвестный тип)")
                    continue

                # Формируем имя файла с уникальным номером
                filename = f"attachment_{attachment_id}.{ext}"

                # Создаём безопасный путь
                filepath = os.path.join(attachments_dir, filename)
                counter = 1
                while os.path.exists(filepath):
                    name, base_ext = os.path.splitext(filename)
                    filepath = os.path.join(attachments_dir, f"{name}_{counter}{base_ext}")
                    counter += 1

                # Сохраняем файл
                with open(filepath, 'wb') as f:
                    f.write(data)

                saved_count += 1
                print(f"    [+] Сохранено вложение: {os.path.basename(filepath)}")

                # Увеличиваем уникальный номер для следующего вложения
                attachment_id += 1

            except Exception as e:
                print(f"    [!] Ошибка при сохранении вложения: {e}")
        # if saved_count ==0:
        #     os.rmdir()
        return saved_count
    except Exception as e:
        print(f"[!] Ошибка при обработке вложений: {e}")
        return 0


def save_message_as_txt(message, output_dir, msg_num):
    """Безопасное сохранение письма с временем в GMT+3"""
    try:
        headers = message.get_transport_headers()
        headers_lines = headers.splitlines() if headers else []

        sender = str(getattr(message, 'sender_name', None)) or "Неизвестный_отправитель"
        subject = str(getattr(message, 'subject', None)) or "Без_темы"


        # Получаем данные из заголовков
        # from_values = get_header_value(headers_lines, 'From')
        to_values = get_header_value(headers_lines, 'To')
        # subject = decode_mime_string(get_header_value(headers_lines, 'Subject'))
        # print(f'Тип subject: {type(subject)}')

        # Форматируем данные
        # sender = ', '.join(from_values)
        receivers = ', '.join(to_values) if to_values else 'Не указаны'
        # subject = subject_values[0] if subject_values else 'Без темы'

        # Конвертируем время в GMT+3
        received_time = convert_to_gmt3(getattr(message, 'delivery_time', None))
        sent_time = convert_to_gmt3(getattr(message, 'client_submit_time', None))

        # Создаем базовое имя файла
        date_part = (received_time or sent_time or datetime.now(GMT3)).strftime('%Y%m%d_%H%M')
        filename_base = f"{date_part}_{sanitize_filename(sender)}_{sanitize_filename(subject)}_{msg_num}"

        # Получаем тело письма
        body = get_message_body(message)

        # Формируем содержимое файла
        content = [
            f"ПАПКА: {get_folder_path(message)}",
            f"НОМЕР: {msg_num}",
            f"ОТПРАВИТЕЛЬ: {sender}",
            f"ПОЛУЧАТЕЛИ: {receivers}",
            f"ТЕМА: {subject}",
            f"ОТПРАВЛЕНО: {format_datetime_gmt3(sent_time)}",
            f"ПОЛУЧЕНО: {format_datetime_gmt3(received_time)}",
            "\nТЕКСТ ПИСЬМА:",
            "=" * 80,
            body,
            "=" * 80
        ]

        # Сохраняем письмо
        filename = f"{filename_base}.txt"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w', encoding='utf-8', errors='replace') as f:
            f.write('\n'.join(content))

        # Обработка вложений
        if hasattr(message, 'attachments') and message.number_of_attachments > 0:
            attachments_dir = os.path.join(output_dir, filename_base)
            os.makedirs(attachments_dir, exist_ok=True)
            saved_attachments = save_attachments(message, attachments_dir)

            if saved_attachments > 0:
                # Обновляем имя файла с учетом вложений
                new_filename = f"{filename_base} ({saved_attachments} вложений)_{msg_num}.txt"
                new_filepath = os.path.join(output_dir, new_filename)
                os.rename(filepath, new_filepath)

                # Обновляем имя папки с вложениями
                new_attachments_dir = os.path.join(output_dir,
                                                   f"{filename_base} ({saved_attachments} вложений)_{msg_num}")
                os.rename(attachments_dir, new_attachments_dir)
            else:
                os.rmdir(attachments_dir)

        print(f"[+] Сохранено письмо #{msg_num}: {os.path.basename(filepath)}")
        return filepath
    except Exception as e:
        print(f"[!] Критическая ошибка при сохранении письма #{msg_num}: {str(e)}")
        return None


def parse_datetime(dt_str):
    """Преобразует строку в datetime с учетом GMT+3"""
    try:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d.%m.%Y', '%d.%m.%Y %H:%M:%S'):
            try:
                dt = datetime.strptime(dt_str, fmt)
                return dt.replace(tzinfo=GMT3)
            except ValueError:
                continue
        return None
    except ValueError:
        return None


def parse_time_range(time_str):
    """Парсит строку с диапазоном времени"""
    try:
        start, end = map(int, time_str.split('-'))
        return start, end
    except Exception as e:
        print(f"[!] Ошибка при обработке диапазона времени {time_str}: {e}")


def search_pst(pst_path, search_criteria, output_dir=None):
    """Основная функция поиска в PST-файле"""
    try:
        print(f"[+] Открываю PST-файл: {pst_path}")
        pst = pypff.file()
        pst.open(pst_path)

        if output_dir:
            ensure_output_dir(output_dir)
            print(f"[+] Найденные письма будут сохранены в: {os.path.abspath(output_dir)}")

        root = pst.get_root_folder()
        print(f"[+] Найдено корневых папок: {root.number_of_sub_folders}")

        total_messages = process_folder(root, search_criteria, 0, output_dir)

        print(f"\n[+] Поиск завершен. Обработано сообщений: {total_messages}")
        if output_dir and os.path.exists(output_dir):
            txt_files = [f for f in os.listdir(output_dir) if f.endswith('.txt')]
            print(f"[+] Сохранено писем: {len(txt_files)}")
        pst.close()
    except IOError as e:
        print(f"[!] Ошибка при открытии файла: {e}")
    except Exception as e:
        print(f"[!] Критическая ошибка: {e}")


def process_folder(folder, search_criteria, counter, output_dir=None):
    """Рекурсивно обрабатывает папки PST"""
    try:
        for message in folder.sub_messages:
            counter += 1
            process_message(message, search_criteria, counter, output_dir)

        for subfolder in folder.sub_folders:
            counter = process_folder(subfolder, search_criteria, counter, output_dir)
    except AttributeError as e:
        print(f"[!] Ошибка доступа к папке: {e}")
    except Exception as e:
        print(f"[!] Ошибка при обработке папки: {e}")
    return counter


def process_message(message, search_criteria, msg_num, output_dir=None):
    """Обрабатывает отдельное сообщение"""
    try:
        # Получаем заголовки сообщения
        headers = message.get_transport_headers()
        headers_lines = headers.splitlines() if headers else []

        # Извлекаем данные из заголовков
        sender_values = get_header_value(headers_lines, 'From')
        receivers_values = get_header_value(headers_lines, 'To')
        subject_values = get_header_value(headers_lines, 'Subject')

        sender = sender_values[0] if sender_values else "Неизвестный отправитель"
        receivers = receivers_values if receivers_values else ["Не указаны"]
        subject = subject_values[0] if subject_values else "Без темы"

        body = get_message_body(message)
        # Конвертируем время в GMT+3
        received_time = convert_to_gmt3(getattr(message, 'delivery_time', None))
        sent_time = convert_to_gmt3(getattr(message, 'client_submit_time', None))

        if not matches_criteria(sender, subject, body,
                                received_time, sent_time, search_criteria):
            return

        print(f"\n[+] Найдено письмо #{msg_num}:")
        print(f"    Отправитель: {sender}")
        print(f"    Получатели: {receivers[0]}")
        if len(receivers) > 1:
            for receiver in receivers[1:]:
                print(' ' * 15 + receiver)
        print(f"    Тема: {subject}")
        if sent_time:
            print(f"    Отправлено: {format_datetime_gmt3(sent_time)}")

        if output_dir:
            save_message_as_txt(message, output_dir, msg_num)
    except Exception as e:
        print(f"[!] Ошибка при обработке сообщения #{msg_num}: {e}")


def main():
    print_header()
    parser = argparse.ArgumentParser(
        description='Поиск в PST-файле с сохранением результатов',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('pst_file', help='Путь к PST-файлу')
    parser.add_argument('--output-dir', required=True,
                        help='Каталог для сохранения найденных писем')
    parser.add_argument('--sender', help='Фильтр по отправителю')
    parser.add_argument('--subject', help='Фильтр по теме письма')
    parser.add_argument('--body', help='Фильтр по тексту письма')
    parser.add_argument('--sent-after', help='Письма, отправленные после указанной даты (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--sent-before', help='Письма, отправленные до указанной даты (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--received-after', help='Письма, полученные после указанной даты (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--received-before', help='Письма, полученные до указанной даты (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--sent-time', help='Диапазон часов отправки (формат: HH-HH, например 8-17 или 22-6)')
    parser.add_argument('--received-time', help='Диапазон часов получения (формат: HH-HH, например 8-17 или 22-6)')

    args = parser.parse_args()
    criteria = {}
    if args.sender: criteria['sender'] = args.sender
    if args.subject: criteria['subject'] = args.subject
    if args.body: criteria['body'] = args.body

    if args.sent_after:
        criteria['sent_after'] = parse_datetime(args.sent_after)
    if args.sent_before:
        criteria['sent_before'] = parse_datetime(args.sent_before)
    if args.received_after:
        criteria['received_after'] = parse_datetime(args.received_after)
    if args.received_before:
        criteria['received_before'] = parse_datetime(args.received_before)

    if args.sent_time:
        time_range = parse_time_range(args.sent_time)
        if time_range:
            criteria['sent_time_range'] = time_range
        else:
            print("[!] Неверный формат диапазона времени для --sent-time")

    if args.received_time:
        time_range = parse_time_range(args.received_time)
        if time_range:
            criteria['received_time_range'] = time_range
        else:
            print("[!] Неверный формат диапазона времени для --received-time")

    search_pst(args.pst_file, criteria, args.output_dir)


if __name__ == '__main__':
    main()
