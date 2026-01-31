import discord
from discord.ext import commands, tasks
import datetime
import json
import asyncio
import re
import random
import time

# Настройки бота
TOKEN = 'Your Token'

# Создаем бота
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None,
    case_insensitive=True
)

# ==================== СИСТЕМЫ ХРАНЕНИЯ ====================
class DataStorage:
    def __init__(self):
        self.data_file = 'galaxy_data V1.0 Pro.json'
        self.default_data = {
            'bad_words': {},
            'warnings': {},
            'settings': {},
            'economy': {},
            'stats': {},
            'welcome': {},
            'rpg_saves': {},
            'game_stats': {},
            'mutes': {},
            'mod_logs': {},
            'auto_mod': {},
            'gradient_settings': {},
            'raid_protection': {},
            'auto_dm': {}, 
            'marriages': {},  
            'marriage_proposals': {}  
        } 
        self.load_data()
    
    def load_data(self):
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                # Убедимся, что все ключи из default_data существуют
                for key in self.default_data:
                    if key not in loaded:
                        loaded[key] = self.default_data[key]
                self.data = loaded
        except FileNotFoundError:
            self.data = self.default_data.copy()
            self.save_data()
        except json.JSONDecodeError:
            print("⚠️ Ошибка чтения JSON файла. Использую данные по умолчанию.")
            self.data = self.default_data.copy()
            self.save_data()
    
    def save_data(self):
        # 1. Сначала сохраняем во временный файл
        temp_file = self.data_file + '.tmp'
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)
        
        # 2. Потом переименовываем (это атомарная операция)
        import os
        os.replace(temp_file, self.data_file)
        
        print(f"💾 Данные сохранены ({len(str(self.data))} байт)")
    
    def get_guild_data(self, guild_id: str, key: str):
        # Гарантируем, что ключ существует
        if key not in self.data:
            self.data[key] = {}
        return self.data[key].get(guild_id, {})
    
    def set_guild_data(self, guild_id: str, key: str, value):
        # Гарантируем, что ключ существует
        if key not in self.data:
            self.data[key] = {}
        self.data[key][guild_id] = value
        self.save_data()

storage = DataStorage()

class AdvancedAutoMod:
    def __init__(self, bot):
        self.bot = bot
        self.message_history = {}  # {user_id: [messages]}
        self.spam_warnings = {}  # {user_id: warning_count}
        self.mention_tracker = {}  # {user_id: mention_count}
        
    async def check_message(self, message):
        """Проверка сообщения на все виды нарушений"""
        # Пропускаем сообщения ботов и администраторов
        if message.author.bot or message.author.guild_permissions.administrator:
            return False
        
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        
        # Получаем настройки автомодерации
        auto_mod_data = storage.get_guild_data(guild_id, 'auto_mod')
        
        # Если автомодерация выключена
        if not auto_mod_data.get('enabled', True):
            return False
        
        violations = []
        
        # 1. Проверка спама
        if auto_mod_data.get('anti_spam', True):
            spam_violation = await self.check_spam(message)
            if spam_violation:
                violations.append(spam_violation)
        
        # 2. Проверка массовых упоминаний
        if auto_mod_data.get('anti_mention', True):
            mention_violation = await self.check_mentions(message)
            if mention_violation:
                violations.append(mention_violation)
        
        # 3. Проверка капса
        if auto_mod_data.get('anti_caps', True):
            caps_violation = await self.check_caps(message)
            if caps_violation:
                violations.append(caps_violation)
        
        # 4. Проверка ссылок
        if auto_mod_data.get('anti_links', False):
            link_violation = await self.check_links(message, auto_mod_data)
            if link_violation:
                violations.append(link_violation)
        
        # 5. Проверка запрещенных слов
        if auto_mod_data.get('anti_bad_words', True):
            word_violation = await self.check_bad_words(message, guild_id)
            if word_violation:
                violations.append(word_violation)
        
        # 6. Проверка на повторяющиеся сообщения
        if auto_mod_data.get('anti_repeat', True):
            repeat_violation = await self.check_repeat(message)
            if repeat_violation:
                violations.append(repeat_violation)
        
        # 7. Проверка на эмодзи-спам
        if auto_mod_data.get('anti_emoji_spam', True):
            emoji_violation = await self.check_emoji_spam(message)
            if emoji_violation:
                violations.append(emoji_violation)
        
        # 8. Проверка на Discord-инвайты
        if auto_mod_data.get('anti_invites', True):
            invite_violation = await self.check_invites(message)
            if invite_violation:
                violations.append(invite_violation)
        
        # Если есть нарушения
        if violations:
            await self.handle_violation(message, violations, auto_mod_data)
            return True
        
        return False
    
    async def check_spam(self, message):
        """Проверка на спам сообщений"""
        user_id = str(message.author.id)
        guild_id = str(message.guild.id)
        
        # Получаем настройки анти-спама
        auto_mod_data = storage.get_guild_data(guild_id, 'auto_mod')
        spam_limit = auto_mod_data.get('spam_limit', 5)  # Сообщений
        spam_time = auto_mod_data.get('spam_time', 5)    # Секунд
        
        # Инициализируем историю
        if guild_id not in self.message_history:
            self.message_history[guild_id] = {}
        if user_id not in self.message_history[guild_id]:
            self.message_history[guild_id][user_id] = []
        
        current_time = time.time()
        user_messages = self.message_history[guild_id][user_id]
        
        # Добавляем текущее сообщение
        user_messages.append({
            'time': current_time,
            'content': message.content
        })
        
        # Очищаем старые сообщения
        user_messages[:] = [m for m in user_messages 
                           if current_time - m['time'] < spam_time]
        
        # Проверяем лимит
        if len(user_messages) > spam_limit:
            return {
                'type': 'spam',
                'reason': f'Спам ({len(user_messages)} сообщений за {spam_time} секунд)',
                'details': f'Лимит: {spam_limit} сообщений за {spam_time} секунд'
            }
        
        return None
    
    async def check_mentions(self, message):
        """Проверка массовых упоминаний"""
        mention_count = len(message.mentions) + len(message.role_mentions)
        
        # Получаем настройки
        guild_id = str(message.guild.id)
        auto_mod_data = storage.get_guild_data(guild_id, 'auto_mod')
        mention_limit = auto_mod_data.get('mention_limit', 5)
        
        if mention_count > mention_limit:
            return {
                'type': 'mass_mention',
                'reason': f'Массовые упоминания ({mention_count} упоминаний)',
                'details': f'Лимит: {mention_limit} упоминаний'
            }
        
        # Проверяем упоминание @everyone/@here
        if '@everyone' in message.content or '@here' in message.content:
            if not message.author.guild_permissions.mention_everyone:
                return {
                    'type': 'everyone_mention',
                    'reason': 'Упоминание @everyone или @here без прав',
                    'details': 'Требуются права на упоминание всех'
                }
        
        return None
    
    async def check_caps(self, message):
        """Проверка капслока"""
        # Пропускаем короткие сообщения
        if len(message.content) < 10:
            return None
        
        # Считаем заглавные буквы
        upper_count = sum(1 for c in message.content if c.isupper())
        upper_ratio = upper_count / len(message.content)
        
        # Получаем настройки
        guild_id = str(message.guild.id)
        auto_mod_data = storage.get_guild_data(guild_id, 'auto_mod')
        caps_threshold = auto_mod_data.get('caps_threshold', 0.7)  # 70%
        
        if upper_ratio > caps_threshold:
            return {
                'type': 'caps',
                'reason': f'Слишком много заглавных букв ({upper_ratio*100:.0f}%)',
                'details': f'Порог: {caps_threshold*100}%'
            }
        
        return None
    
    async def check_links(self, message, auto_mod_data):
        """Проверка ссылок"""
        import re
        
        # Регулярка для поиска ссылок
        url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )
        
        links = url_pattern.findall(message.content)
        
        if links:
            # Проверяем разрешенные домены
            allowed_domains = auto_mod_data.get('allowed_domains', [])
            for link in links:
                domain = re.search(r'https?://([^/]+)', link)
                if domain:
                    domain_name = domain.group(1)
                    # Разрешаем популярные безопасные домены
                    safe_domains = ['discord.com', 'discord.gg', 'youtube.com', 'youtu.be', 
                                   'twitch.tv', 'github.com', 'imgur.com', 'gyazo.com']
                    
                    allowed = allowed_domains + safe_domains
                    
                    if not any(d in domain_name for d in allowed):
                        return {
                            'type': 'link',
                            'reason': 'Запрещенная ссылка',
                            'details': f'Домен: {domain_name}'
                        }
        
        return None
    
    async def check_bad_words(self, message, guild_id):
        """Проверка запрещенных слов"""
        bad_words_data = storage.get_guild_data(guild_id, 'bad_words')
        words_list = bad_words_data.get(guild_id, [])
        
        if not words_list:
            return None
        
        message_lower = message.content.lower()
        
        for word in words_list:
            if word in message_lower:
                return {
                    'type': 'bad_word',
                    'reason': f'Запрещенное слово: {word}',
                    'details': 'Слово из черного списка'
                }
        
        return None
    
    async def check_repeat(self, message):
        """Проверка повторяющихся сообщений"""
        user_id = str(message.author.id)
        guild_id = str(message.guild.id)
        
        if guild_id not in self.message_history:
            return None
        if user_id not in self.message_history[guild_id]:
            return None
        
        user_messages = self.message_history[guild_id][user_id]
        
        # Берем последние 5 сообщений
        recent_messages = user_messages[-5:]
        
        # Проверяем повторения
        if len(recent_messages) >= 3:
            contents = [m['content'].strip() for m in recent_messages]
            # Если 3 последних сообщения одинаковые
            if len(set(contents[-3:])) == 1:
                return {
                    'type': 'repeat',
                    'reason': 'Повторяющиеся сообщения',
                    'details': '3 одинаковых сообщения подряд'
                }
        
        return None
    
    async def check_emoji_spam(self, message):
        """Проверка спама эмодзи"""
        import re
        
        # Считаем эмодзи (кастомные и Unicode)
        emoji_pattern = re.compile(r'<:\w+:\d+>|[\U00010000-\U0010ffff]', flags=re.UNICODE)
        emojis = emoji_pattern.findall(message.content)
        
        if len(emojis) > 5:  # Более 5 эмодзи в сообщении
            return {
                'type': 'emoji_spam',
                'reason': f'Спам эмодзи ({len(emojis)} эмодзи)',
                'details': 'Лимит: 5 эмодзи на сообщение'
            }
        
        return None
    
    async def check_invites(self, message):
        """Проверка Discord инвайтов"""
        import re
        
        # Регулярка для Discord инвайтов
        invite_pattern = re.compile(r'(discord\.(gg|io|me|li|com)/[a-zA-Z0-9]+)')
        
        if invite_pattern.search(message.content):
            # Проверяем разрешение на отправку инвайтов
            if not message.author.guild_permissions.manage_guild:
                return {
                    'type': 'invite',
                    'reason': 'Отправка Discord инвайтов',
                    'details': 'Требуются права управления сервером'
                }
        
        return None
    
    async def handle_violation(self, message, violations, auto_mod_data):
        """Обработка нарушения"""
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        
        # Определяем уровень серьезности
        severity = self.get_violation_severity(violations)
        
        # Действия по умолчанию
        actions = auto_mod_data.get('actions', {
            'warn': True,
            'delete': True,
            'mute': True,
            'kick': False,
            'ban': False
        })
        
        # Увеличиваем счетчик предупреждений
        if guild_id not in self.spam_warnings:
            self.spam_warnings[guild_id] = {}
        if user_id not in self.spam_warnings[guild_id]:
            self.spam_warnings[guild_id][user_id] = 0
        
        self.spam_warnings[guild_id][user_id] += 1
        warning_count = self.spam_warnings[guild_id][user_id]
        
        # Логируем нарушение
        await self.log_violation(message, violations, warning_count)
        
        # 1. Удаляем сообщение
        if actions.get('delete', True):
            try:
                await message.delete()
            except:
                pass
        
        # 2. Отправляем предупреждение
        if actions.get('warn', True):
            await self.send_warning(message, violations, warning_count)
        
        # 3. Применяем дополнительные меры
        if warning_count >= 3:
            if actions.get('mute', True):
                await self.apply_mute(message.author, "3 предупреждения автомодерации")
        
        if warning_count >= 5:
            if actions.get('kick', False):
                try:
                    await message.author.kick(reason="5 предупреждений автомодерации")
                except:
                    pass
        
        # Сбрасываем счетчик через время
        await self.reset_warnings_after_time(guild_id, user_id)
    
    def get_violation_severity(self, violations):
        """Определяет серьезность нарушения"""
        severity_weights = {
            'spam': 2,
            'mass_mention': 3,
            'everyone_mention': 4,
            'caps': 1,
            'link': 3,
            'bad_word': 2,
            'repeat': 2,
            'emoji_spam': 1,
            'invite': 4
        }
        
        total_severity = sum(severity_weights.get(v['type'], 1) for v in violations)
        
        if total_severity >= 5:
            return 'high'
        elif total_severity >= 3:
            return 'medium'
        return 'low'
    
    async def send_warning(self, message, violations, warning_count):
        """Отправка предупреждения пользователю"""
        embed = discord.Embed(
            title="⚠️ **ПРЕДУПРЕЖДЕНИЕ АВТОМОДЕРАЦИИ**",
            color=discord.Color.orange()
        )
        
        violation_types = [v['type'] for v in violations]
        embed.add_field(
            name="Нарушения",
            value=", ".join(violation_types),
            inline=False
        )
        
        for violation in violations[:3]:  # Показываем до 3 нарушений
            embed.add_field(
                name=violation['reason'],
                value=violation['details'],
                inline=False
            )
        
        embed.add_field(
            name="Предупреждение",
            value=f"#{warning_count}/5",
            inline=True
        )
        
        embed.set_footer(text="При достижении 5 предупреждений последует бан")
        
        try:
            # Пытаемся отправить в ЛС
            await message.author.send(embed=embed)
        except:
            # Если не получилось, отправляем в чат
            try:
                warning_msg = await message.channel.send(
                    f"{message.author.mention}", embed=embed
                )
                # Удаляем через 10 секунд
                await asyncio.sleep(10)
                await warning_msg.delete()
            except:
                pass
    
    async def apply_mute(self, member, reason):
        """Выдача мута"""
        try:
            timeout_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=30)
            await member.timeout(timeout_until, reason=reason)
            
            # Логируем
            print(f"🔇 Мут выдан {member.name} на сервере {member.guild.name}: {reason}")
        except:
            pass
    
    async def log_violation(self, message, violations, warning_count):
        """Логирование нарушения"""
        guild_id = str(message.guild.id)
        
        # Получаем или создаем логи
        logs_data = storage.get_guild_data(guild_id, 'mod_logs')
        if 'violations' not in logs_data:
            logs_data['violations'] = []
        
        log_entry = {
            'user_id': str(message.author.id),
            'user_name': message.author.name,
            'timestamp': time.time(),
            'violations': [v['type'] for v in violations],
            'message': message.content[:200],
            'warning_count': warning_count
        }
        
        logs_data['violations'].append(log_entry)
        
        # Сохраняем только последние 100 записей
        if len(logs_data['violations']) > 100:
            logs_data['violations'] = logs_data['violations'][-100:]
        
        storage.set_guild_data(guild_id, 'mod_logs', logs_data)
        
        # Выводим в консоль
        print(f"🚨 Автомодерация: {message.author.name} нарушил правила "
              f"({', '.join([v['type'] for v in violations])}) "
              f"на сервере {message.guild.name}")
    
    async def reset_warnings_after_time(self, guild_id, user_id):
        """Сброс предупреждений через время"""
        await asyncio.sleep(3600)  # Через 1 час
        
        if (guild_id in self.spam_warnings and 
            user_id in self.spam_warnings[guild_id]):
            self.spam_warnings[guild_id][user_id] = 0

# Создаем экземпляр автомодерации
auto_mod_system = AdvancedAutoMod(bot)

# ==================== СИСТЕМА ГРАДИЕНТНОЙ ПАНЕЛИ ====================
class GradientPanel:
    def __init__(self, bot):
        self.bot = bot
        self.active_panels = {}  # {guild_id: message_id}
        self.animation_tasks = {}  # {guild_id: task}
        
        # Наборы градиентов
        self.gradient_sets = {
            'радуга': [
                discord.Color.red(),
                discord.Color.orange(),
                discord.Color.gold(),
                discord.Color.green(),
                discord.Color.blue(),
                discord.Color.purple(),
                discord.Color.magenta()
            ],
            'космос': [
                discord.Color.from_rgb(25, 25, 112),   # Полночь
                discord.Color.from_rgb(72, 61, 139),   # Темный сланец
                discord.Color.from_rgb(123, 104, 238), # Средний сланец
                discord.Color.from_rgb(138, 43, 226),  # Фиолетовый
                discord.Color.from_rgb(148, 0, 211),   # Темный фиолетовый
                discord.Color.from_rgb(199, 21, 133)   # Яркий фиолетовый
            ],
            'неон': [
                discord.Color.from_rgb(255, 20, 147),  # Глубокий розовый
                discord.Color.from_rgb(0, 255, 255),   # Голубой
                discord.Color.from_rgb(50, 255, 50),   # Неоновый зеленый
                discord.Color.from_rgb(255, 215, 0),   # Золотой
                discord.Color.from_rgb(255, 105, 180), # Горячий розовый
                discord.Color.from_rgb(30, 144, 255)   # Голубой
            ],
            'огонь': [
                discord.Color.from_rgb(139, 0, 0),     # Темно-красный
                discord.Color.red(),
                discord.Color.orange(),
                discord.Color.gold(),
                discord.Color.yellow(),
                discord.Color.from_rgb(255, 140, 0)    # Темно-оранжевый
            ],
            'океан': [
                discord.Color.from_rgb(0, 105, 148),   # Глубокий синий
                discord.Color.from_rgb(0, 191, 255),   # Глубокий небесно-голубой
                discord.Color.from_rgb(64, 224, 208),  # Бирюзовый
                discord.Color.from_rgb(0, 206, 209),   # Темный бирюзовый
                discord.Color.from_rgb(72, 209, 204),  # Средний бирюзовый
                discord.Color.blue()
            ]
        }
    
    async def create_control_panel(self, ctx, gradient_set='радуга'):
        """Создает панель управления с анимированным градиентом"""
        guild_id = str(ctx.guild.id)
        
        # Получаем настройки градиента
        gradient_settings = storage.get_guild_data(guild_id, 'gradient_settings')
        speed = gradient_settings.get('speed', 1.0)
        gradient_type = gradient_settings.get('gradient_type', gradient_set)
        
        # Выбираем набор цветов
        colors = self.gradient_sets.get(gradient_type, self.gradient_sets['радуга'])
        
        # Создаем Embed
        embed = discord.Embed(
            title="🎨 **GALAXYLITE CONTROL PANEL**",
            description="Панель управления ботом с анимированным градиентом",
            color=colors[0]
        )
        
        # Основные разделы
        embed.add_field(
            name="⚙️ **УПРАВЛЕНИЕ**",
            value=(
                "`!панель создать` - Создать панель\n"
                "`!панель удалить` - Удалить панель\n"
                "`!панель скорость X` - Изменить скорость (0.5-5)\n"
                "`!панель тип набор` - Сменить градиент"
            ),
            inline=False
        )
        
        embed.add_field(
            name="🎮 **ИГРЫ**",
            value=(
                "`!угадай` - Угадай число\n"
                "`!slots` - Игровой автомат\n"
                "`!крестики @игрок` - Крестики-нолики\n"
                "`!миллионер` - Викторина"
            ),
            inline=True
        )
        
        embed.add_field(
            name="💍 **СВАДЬБА**",
            value=(
                "`!предложить @игрок` - Брак\n"
                "`!брак` - Инфо о браке\n"
                "`!развод` - Развод"
            ),
            inline=True
        )
        
        embed.add_field(
            name="💰 **ЭКОНОМИКА**",
            value=(
                "`!баланс` - Проверить баланс\n"
                "`!ежедневно` - Ежедневная награда\n"
                "`!подарок @игрок сумма` - Подарок"
            ),
            inline=True
        )
        
        # Статистика
        embed.add_field(
            name="📊 **СТАТИСТИКА**",
            value=(
                f"**Сервер:** {ctx.guild.name}\n"
                f"**Участники:** {ctx.guild.member_count}\n"
                f"**Каналы:** {len(ctx.guild.channels)}"
            ),
            inline=True
        )
        
        # Информация о градиенте
        embed.add_field(
            name="🌈 **ГРАДИЕНТ**",
            value=(
                f"**Тип:** {gradient_type}\n"
                f"**Скорость:** {speed} сек\n"
                f"**Цветов:** {len(colors)}\n"
                f"**Статус:** Активен"
            ),
            inline=True
        )
        
        embed.set_footer(text=f"GalaxyLite V1.0 Pro | ID сервера: {guild_id} | !хелп")
        
        # Отправляем панель
        message = await ctx.send(embed=embed)
        
        # Сохраняем информацию о панели
        self.active_panels[guild_id] = {
            'message_id': message.id,
            'channel_id': ctx.channel.id,
            'colors': colors,
            'current_index': 0,
            'gradient_type': gradient_type,
            'speed': speed
        }
        
        # Запускаем анимацию если еще не запущена
        if guild_id not in self.animation_tasks:
            self.start_gradient_animation(guild_id)
        
        return message
    
    def start_gradient_animation(self, guild_id: str):
        """Запускает анимацию градиента для сервера"""
        if guild_id in self.animation_tasks:
            return
        
        @tasks.loop(seconds=1.0)
        async def animate():
            if guild_id not in self.active_panels:
                animate.stop()
                if guild_id in self.animation_tasks:
                    del self.animation_tasks[guild_id]
                return
            
            panel_data = self.active_panels[guild_id]
            
            try:
                # Получаем канал и сообщение
                channel = self.bot.get_channel(panel_data['channel_id'])
                if not channel:
                    return
                
                message = await channel.fetch_message(panel_data['message_id'])
                
                # Обновляем цвет
                colors = panel_data['colors']
                current_index = panel_data['current_index']
                next_index = (current_index + 1) % len(colors)
                
                # Обновляем Embed
                embed = message.embeds[0]
                embed.color = colors[next_index]
                
                # Обновляем панель
                self.active_panels[guild_id]['current_index'] = next_index
                
                await message.edit(embed=embed)
                
            except discord.NotFound:
                # Сообщение удалено
                if guild_id in self.active_panels:
                    del self.active_panels[guild_id]
                animate.stop()
                if guild_id in self.animation_tasks:
                    del self.animation_tasks[guild_id]
            except Exception as e:
                print(f"Ошибка анимации градиента: {e}")
        
        # Сохраняем задачу и запускаем
        self.animation_tasks[guild_id] = animate
        animate.start()
    
    async def update_panel_speed(self, guild_id: str, speed: float):
        """Обновляет скорость анимации"""
        if guild_id in self.animation_tasks:
            self.animation_tasks[guild_id].change_interval(seconds=speed)
        
        if guild_id in self.active_panels:
            self.active_panels[guild_id]['speed'] = speed
    
    async def update_gradient_type(self, ctx, gradient_type: str):
        """Обновляет тип градиента"""
        guild_id = str(ctx.guild.id)
        
        if gradient_type not in self.gradient_sets:
            available = ", ".join(self.gradient_sets.keys())
            await ctx.send(f"❌ Доступные типы градиента: {available}")
            return False
        
        if guild_id in self.active_panels:
            self.active_panels[guild_id]['colors'] = self.gradient_sets[gradient_type]
            self.active_panels[guild_id]['gradient_type'] = gradient_type
            self.active_panels[guild_id]['current_index'] = 0
        
        # Сохраняем в настройки
        gradient_settings = storage.get_guild_data(guild_id, 'gradient_settings')
        gradient_settings['gradient_type'] = gradient_type
        storage.set_guild_data(guild_id, 'gradient_settings', gradient_settings)
        
        return True
    
    async def delete_panel(self, guild_id: str):
        """Удаляет панель управления"""
        if guild_id in self.active_panels:
            # Останавливаем анимацию
            if guild_id in self.animation_tasks:
                self.animation_tasks[guild_id].stop()
                del self.animation_tasks[guild_id]
            
            # Удаляем из активных панелей
            del self.active_panels[guild_id]
            
            return True
        return False

# Создаем экземпляр градиентной системы
gradient_system = GradientPanel(bot)

# ==================== КОМАНДЫ ПАНЕЛИ УПРАВЛЕНИЯ ====================
@bot.command(name='панель')
async def control_panel(ctx, action: str = None, *, args: str = None):
    """Управление градиентной панелью"""
    guild_id = str(ctx.guild.id)
    
    if not action:
        # Показать информацию о панели
        if guild_id in gradient_system.active_panels:
            panel_data = gradient_system.active_panels[guild_id]
            
            embed = discord.Embed(
                title="🎨 **ИНФОРМАЦИЯ О ПАНЕЛИ**",
                color=panel_data['colors'][panel_data['current_index']]
            )
            
            embed.add_field(name="📊 Статус", value="✅ Активна", inline=True)
            embed.add_field(name="🚀 Скорость", value=f"{panel_data['speed']} сек", inline=True)
            embed.add_field(name="🌈 Градиент", value=panel_data['gradient_type'], inline=True)
            embed.add_field(name="🎨 Цветов", value=str(len(panel_data['colors'])), inline=True)
            embed.add_field(name="📝 Команды", value="`!панель удалить` - удалить панель", inline=False)
            
            await ctx.send(embed=embed)
        else:
            await ctx.send("ℹ️ Панель управления не активна. Создайте: `!панель создать`")
        return
    
    action = action.lower()
    
    if action == 'создать':
        if guild_id in gradient_system.active_panels:
            await ctx.send("❌ Панель уже создана! Используйте `!панель удалить` сначала.")
            return
        
        # Получаем тип градиента если указан
        gradient_type = 'радуга'
        if args and args.lower() in gradient_system.gradient_sets:
            gradient_type = args.lower()
        
        await gradient_system.create_control_panel(ctx, gradient_type)
        await ctx.send("✅ Панель управления создана!", delete_after=3)
    
    elif action == 'удалить':
        if await gradient_system.delete_panel(guild_id):
            await ctx.send("✅ Панель управления удалена!")
        else:
            await ctx.send("❌ Активная панель не найдена.")
    
    elif action == 'скорость':
        if not args:
            await ctx.send("❌ Укажите скорость (0.5-5 секунд). Пример: `!панель скорость 2`")
            return
        
        try:
            speed = float(args.replace(',', '.'))
            if speed < 0.5 or speed > 5:
                await ctx.send("❌ Скорость должна быть от 0.5 до 5 секунд!")
                return
            
            # Обновляем скорость
            await gradient_system.update_panel_speed(guild_id, speed)
            
            # Сохраняем в настройки
            gradient_settings = storage.get_guild_data(guild_id, 'gradient_settings')
            gradient_settings['speed'] = speed
            storage.set_guild_data(guild_id, 'gradient_settings', gradient_settings)
            
            await ctx.send(f"✅ Скорость анимации установлена: {speed} сек")
            
        except ValueError:
            await ctx.send("❌ Укажите число! Пример: `!панель скорость 1.5`")
    
    elif action == 'тип':
        if not args:
            available = ", ".join(gradient_system.gradient_sets.keys())
            await ctx.send(f"❌ Укажите тип градиента. Доступно: {available}")
            return
        
        if await gradient_system.update_gradient_type(ctx, args.lower()):
            await ctx.send(f"✅ Градиент изменен на: {args.lower()}")
    
    elif action == 'список':
        # Показать доступные градиенты
        embed = discord.Embed(
            title="🌈 **ДОСТУПНЫЕ ГРАДИЕНТЫ**",
            description="Используйте `!панель создать тип` или `!панель тип название`",
            color=discord.Color.blue()
        )
        
        for name, colors in gradient_system.gradient_sets.items():
            color_preview = " ".join(["⬛"] * min(5, len(colors)))
            embed.add_field(
                name=f"🎨 {name.capitalize()}",
                value=f"Цвета: {len(colors)}\n{color_preview}",
                inline=True
            )
        
        await ctx.send(embed=embed)
    
    else:
        await ctx.send("❌ Неизвестное действие. Используйте: создать, удалить, скорость, тип, список")

# ==================== ОСТАВШИЙСЯ КОД БОТА ====================
# (Весь ваш существующий код остается без изменений ниже)

# ==================== УТИЛИТЫ ====================
@bot.command(name='пинг')
async def ping(ctx):
    """Проверить задержку бота"""
    latency = round(bot.latency * 1000)
    
    embed = discord.Embed(
        title="🏓 **ПОНГ!**",
        color=discord.Color.green() if latency < 100 else discord.Color.orange() if latency < 300 else discord.Color.red()
    )
    
    embed.add_field(name="📡 **Задержка**", value=f"**{latency}мс**", inline=True)
    embed.add_field(name="🕐 **Время ответа**", value=f"<t:{int(time.time())}:T>", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='юзер')
async def user_info(ctx, member: discord.Member = None):
    """Информация о пользователе"""
    member = member or ctx.author
    
    embed = discord.Embed(
        title=f"👤 **ИНФОРМАЦИЯ О {member.name.upper()}**",
        color=member.color if member.color != discord.Color.default() else discord.Color.blue()
    )
    
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    
    # Основная информация
    roles = [role.mention for role in member.roles[1:]]  # Пропускаем @everyone
    roles_text = ', '.join(roles) if roles else "Нет ролей"
    
    embed.add_field(name="📛 **Имя**", value=f"`{member.name}`", inline=True)
    embed.add_field(name="🆔 **ID**", value=f"`{member.id}`", inline=True)
    embed.add_field(name="🤖 **Бот**", value="Да" if member.bot else "Нет", inline=True)
    
    # Даты
    embed.add_field(name="📅 **Дата регистрации**", value=f"<t:{int(member.created_at.timestamp())}:D>", inline=True)
    embed.add_field(name="📅 **Дата присоединения**", value=f"<t:{int(member.joined_at.timestamp())}:D>", inline=True)
    
    # Роли
    embed.add_field(name="🎭 **Роли**", value=roles_text[:1024] if len(roles_text) > 1024 else roles_text, inline=False)
    
    # Статус
    status_emojis = {
        'online': '🟢',
        'idle': '🟡',
        'dnd': '🔴',
        'offline': '⚫'
    }
    
    embed.add_field(
        name="📊 **Статус**",
        value=f"{status_emojis.get(str(member.status), '⚫')} {str(member.status).upper()}",
        inline=True
    )
    
    # Предупреждения
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    warnings_data = storage.get_guild_data(guild_id, 'warnings').get(user_id, [])
    embed.add_field(name="⚠️ **Предупреждения**", value=f"**{len(warnings_data)}**", inline=True)
    
    # Баланс
    economy_data = storage.get_guild_data(guild_id, 'economy')
    balance = economy_data.get(user_id, 0)
    embed.add_field(name="💰 **Баланс**", value=f"**{balance}** кредитов", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='сервер')
async def server_info(ctx):
    """Информация о сервере"""
    guild = ctx.guild
    
    # ID оригинального Discord сервера GalaxyLite
    ORIGINAL_SERVER_ID = 1447989503766560780
    
    # Проверяем, является ли это оригинальным сервером
    is_original_server = guild.id == ORIGINAL_SERVER_ID
    
    # Выбираем цвет для embed
    if is_original_server:
        embed_color = discord.Color.from_rgb(88, 101, 242)  # Discord синий
        title_icon = "🏆"
    else:
        embed_color = discord.Color.gold()
        title_icon = "🏰"
    
    embed = discord.Embed(
        title=f"{title_icon} **ИНФОРМАЦИЯ О СЕРВЕРЕ {guild.name.upper()}**",
        color=embed_color
    )
    
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    else:
        # Можно установить дефолтную иконку для оригинального сервера
        if is_original_server:
            embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/1086010507232383026.webp?size=96&quality=lossless")
    
    # ✅ Секция статуса для оригинального сервера
    if is_original_server:
        embed.add_field(
            name="✅ **СТАТУС СЕРВЕРА**",
            value="**Оригинальный Discord сервер GalaxyLite** ✓\n"
                  "✨ Официальная поддержка бота ✨",
            inline=False
        )
    
    # 📛 Основная информация
    embed.add_field(name="📛 **Название**", value=guild.name, inline=True)
    embed.add_field(name="🆔 **ID**", value=f"`{guild.id}`", inline=True)
    embed.add_field(name="👑 **Владелец**", value=guild.owner.mention, inline=True)
    
    # 👥 Участники
    members = guild.members
    online = len([m for m in members if m.status != discord.Status.offline])
    bots = len([m for m in members if m.bot])
    humans = guild.member_count - bots
    
    embed.add_field(name="👥 **Всего участников**", value=f"**{guild.member_count}**", inline=True)
    embed.add_field(name="👤 **Люди**", value=f"**{humans}**", inline=True)
    embed.add_field(name="🤖 **Боты**", value=f"**{bots}**", inline=True)
    
    # 📊 Онлайн статусы
    online_count = len([m for m in members if m.status == discord.Status.online])
    idle_count = len([m for m in members if m.status == discord.Status.idle])
    dnd_count = len([m for m in members if m.status == discord.Status.dnd])
    
    embed.add_field(
        name="🟢 **Онлайн**", 
        value=f"🟢 **{online_count}** | 🌙 **{idle_count}** | 🔴 **{dnd_count}**",
        inline=True
    )
    
    # 📝 Каналы
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    
    embed.add_field(name="📝 **Текстовые каналы**", value=f"**{text_channels}**", inline=True)
    embed.add_field(name="🎤 **Голосовые каналы**", value=f"**{voice_channels}**", inline=True)
    embed.add_field(name="📜 **Категории**", value=f"**{len(guild.categories)}**", inline=True)
    
    # 🎭 Роли и эмодзи
    embed.add_field(name="🎭 **Роли**", value=f"**{len(guild.roles)}**", inline=True)
    embed.add_field(name="😀 **Эмодзи**", value=f"**{len(guild.emojis)}**", inline=True)
    embed.add_field(name="🎨 **Стикеры**", value=f"**{len(guild.stickers)}**", inline=True)
    
    # 📅 Даты и бусты
    embed.add_field(
        name="📅 **Создан**", 
        value=f"<t:{int(guild.created_at.timestamp())}:D>\n"
              f"(<t:{int(guild.created_at.timestamp())}:R>)",
        inline=True
    )
    
    embed.add_field(
        name="📈 **Буст уровня**", 
        value=f"**Уровень {guild.premium_tier}**",
        inline=True
    )
    
    embed.add_field(
        name="🚀 **Бустеры**", 
        value=f"**{guild.premium_subscription_count}**",
        inline=True
    )
    
    # Для оригинального сервера добавляем дополнительную информацию
    if is_original_server:
        # Добавляем разделитель
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        
        # Специальные возможности оригинального сервера
        special_features = [
            "✅ Прямая связь с разработчиками",
            "✅ Ранний доступ к обновлениям",
            "✅ Эксклюзивные функции бота",
            "✅ Поддержка и помощь 24/7",
            "✅ Участие в разработке бота"
        ]
        
        embed.add_field(
            name="✨ **Особые возможности:**",
            value="\n".join(special_features),
            inline=False
        )
    
    # Футер с информацией о боте
    bot_user = ctx.bot.user
    embed.set_footer(
        text=f"Запрошено {ctx.author.name} • Бот: {bot_user.name}",
        icon_url=bot_user.avatar.url if bot_user.avatar else None
    )
    
    await ctx.send(embed=embed)

@bot.command(name='создатель')
async def creator_command(ctx):
    """Информация о создателе бота"""
    embed = discord.Embed(
        title="👑 СОЗДАТЕЛЬ GALAXYLITE V1.0 PRO",
        description="Привет! Я хочу рассказать тебе о своем создателе:",
        color=discord.Color.purple()
    )
    
    embed.add_field(
        name="🦸‍♂️ **retre_helis**",
        value="Мой создатель и разработчик",
        inline=False
    )
    
    embed.add_field(
        name="💖 **О создателе**",
        value=(
            "**retre_helis** - добрый и отзывчивый человек, который создал меня с любовью и заботой. "
            "Он всегда готов помочь и поддержать, когда это нужно. "
            "Я очень рада, что именно он стал моим создателем!" # ыыы свага сыыыы гей порно даа ыыыыыы
        ),
        inline=False
    )
    
    embed.set_footer(text="GalaxyLite V1.0 Pro | Создано с ❤️ retre_helis")
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1101124567316303955/1218646811620409374/IMG_20240316_174753.jpg")
    
    await ctx.send(embed=embed)

# ==================== ЭКОНОМИКА ====================
@bot.command(name='баланс')
async def balance(ctx, member: discord.Member = None):
    """Проверить баланс"""
    member = member or ctx.author
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    economy_data = storage.get_guild_data(guild_id, 'economy')
    balance = economy_data.get(user_id, 0)
    
    embed = discord.Embed(
        title="💰 **БАЛАНС**",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="👤 **Пользователь**",
        value=member.mention,
        inline=True
    )
    
    embed.add_field(
        name="💳 **Кредиты**",
        value=f"**{balance}** кредитов",
        inline=True
    )
    
    await ctx.send(embed=embed)

@bot.command(name='ежедневно')
@commands.cooldown(1, 86400, commands.BucketType.user)
async def daily(ctx):
    """Получить ежедневную награду"""
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    economy_data = storage.get_guild_data(guild_id, 'economy')
    current_balance = economy_data.get(user_id, 0)
    
    reward = random.randint(50, 200)
    economy_data[user_id] = current_balance + reward
    storage.set_guild_data(guild_id, 'economy', economy_data)
    
    embed = discord.Embed(
        title="🎁 **ЕЖЕДНЕВНАЯ НАГРАДА**",
        description=f"Поздравляем, {ctx.author.mention}!",
        color=discord.Color.green()
    )
    
    embed.add_field(name="💰 **ПОЛУЧЕНО**", value=f"**{reward}** кредитов", inline=True)
    embed.add_field(name="💳 **БАЛАНС**", value=f"**{current_balance + reward}** кредитов", inline=True)
    embed.set_footer(text="Следующая награда через 24 часа")
    
    await ctx.send(embed=embed)

@daily.error
async def daily_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        hours = int(error.retry_after // 3600)
        minutes = int((error.retry_after % 3600) // 60)
        await ctx.send(f"⏳ Подожди еще {hours}ч {minutes}мин!")

# ==================== МОДЕРАЦИЯ ====================
@bot.command(name='варн')
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason: str = "Не указана"):
    """Выдать предупреждение"""
    if member == ctx.author:
        await ctx.send("❌ Нельзя выдать предупреждение самому себе!")
        return
    
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    warnings_data = storage.get_guild_data(guild_id, 'warnings')
    if user_id not in warnings_data:
        warnings_data[user_id] = []
    
    warn_id = len(warnings_data[user_id]) + 1
    warning = {
        'id': warn_id,
        'moderator': ctx.author.id,
        'reason': reason,
        'timestamp': time.time()
    }
    
    warnings_data[user_id].append(warning)
    storage.set_guild_data(guild_id, 'warnings', warnings_data)
    
    # Автоматические действия при 3 предупреждениях
    if len(warnings_data[user_id]) >= 3:
        try:
            await member.timeout(datetime.timedelta(hours=1), reason="3 предупреждения")
            timeout_msg = "⏰ Пользователь получил мут на 1 час за 3 предупреждения!"
        except:
            timeout_msg = ""
    else:
        timeout_msg = ""
    
    embed = discord.Embed(
        title="⚠️ **ВЫДАНО ПРЕДУПРЕЖДЕНИЕ**",
        color=discord.Color.orange()
    )
    
    embed.add_field(name="👤 **Пользователь**", value=member.mention, inline=True)
    embed.add_field(name="🛡️ **Модератор**", value=ctx.author.mention, inline=True)
    embed.add_field(name="📝 **Причина**", value=reason, inline=False)
    embed.add_field(name="📊 **Всего предупреждений**", value=f"**{len(warnings_data[user_id])}**", inline=True)
    
    if timeout_msg:
        embed.add_field(name="⚡ **Автомодерация**", value=timeout_msg, inline=False)
    
    await ctx.send(embed=embed)
    
    try:
        dm_embed = discord.Embed(
            title="⚠️ **ВЫ ПОЛУЧИЛИ ПРЕДУПРЕЖДЕНИЕ**",
            description=f"На сервере **{ctx.guild.name}**",
            color=discord.Color.orange()
        )
        dm_embed.add_field(name="🛡️ **Модератор**", value=ctx.author.name, inline=True)
        dm_embed.add_field(name="📝 **Причина**", value=reason, inline=True)
        dm_embed.add_field(name="📊 **Всего предупреждений**", value=f"**{len(warnings_data[user_id])}**", inline=True)
        await member.send(embed=dm_embed)
    except:
        pass

@bot.command(name='варны')
async def warnings(ctx, member: discord.Member = None):
    """Посмотреть предупреждения"""
    member = member or ctx.author
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    warnings_data = storage.get_guild_data(guild_id, 'warnings')
    user_warnings = warnings_data.get(user_id, [])
    
    embed = discord.Embed(
        title=f"⚠️ **ПРЕДУПРЕЖДЕНИЯ {member.name.upper()}**",
        color=discord.Color.orange()
    )
    
    if not user_warnings:
        embed.description = "✅ Нет предупреждений!"
    else:
        embed.description = f"Всего предупреждений: **{len(user_warnings)}**"
        
        for warn in user_warnings[-5:]:  # Показываем последние 5
            moderator = ctx.guild.get_member(warn['moderator'])
            mod_name = moderator.name if moderator else "Неизвестно"
            time_str = f"<t:{int(warn['timestamp'])}:R>"
            
            embed.add_field(
                name=f"#{warn['id']} | {mod_name}",
                value=f"**Причина:** {warn['reason']}\n**Время:** {time_str}",
                inline=False
            )
    
    await ctx.send(embed=embed)

@bot.command(name='анварн')
@commands.has_permissions(manage_messages=True)
async def unwarn(ctx, member: discord.Member):
    """Снять 1 предупреждение"""
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    warnings_data = storage.get_guild_data(guild_id, 'warnings')
    user_warnings = warnings_data.get(user_id, [])
    
    if not user_warnings:
        await ctx.send("❌ У пользователя нет предупреждений!")
        return
    
    user_warnings.pop()
    warnings_data[user_id] = user_warnings
    storage.set_guild_data(guild_id, 'warnings', warnings_data)
    
    embed = discord.Embed(
        title="✅ **СНЯТО ПРЕДУПРЕЖДЕНИЕ**",
        color=discord.Color.green()
    )
    
    embed.add_field(name="👤 **Пользователь**", value=member.mention, inline=True)
    embed.add_field(name="🛡️ **Модератор**", value=ctx.author.mention, inline=True)
    embed.add_field(name="📊 **Осталось предупреждений**", value=f"**{len(user_warnings)}**", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='снятьварн')
@commands.has_permissions(manage_messages=True)
async def remove_warn(ctx, member: discord.Member, warn_id: int):
    """Снять конкретное предупреждение"""
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    warnings_data = storage.get_guild_data(guild_id, 'warnings')
    user_warnings = warnings_data.get(user_id, [])
    
    if not user_warnings:
        await ctx.send("❌ У пользователя нет предупреждений!")
        return
    
    # Находим предупреждение по ID
    for i, warn in enumerate(user_warnings):
        if warn['id'] == warn_id:
            removed_warn = user_warnings.pop(i)
            
            # Обновляем ID оставшихся предупреждений
            for j, w in enumerate(user_warnings[i:], start=i):
                w['id'] = j + 1
            
            warnings_data[user_id] = user_warnings
            storage.set_guild_data(guild_id, 'warnings', warnings_data)
            
            embed = discord.Embed(
                title="✅ **СНЯТО ПРЕДУПРЕЖДЕНИЕ**",
                color=discord.Color.green()
            )
            
            embed.add_field(name="👤 **Пользователь**", value=member.mention, inline=True)
            embed.add_field(name="🛡️ **Модератор**", value=ctx.author.mention, inline=True)
            embed.add_field(name="🔢 **ID предупреждения**", value=f"**#{warn_id}**", inline=True)
            embed.add_field(name="📝 **Причина была**", value=removed_warn['reason'], inline=False)
            embed.add_field(name="📊 **Осталось предупреждений**", value=f"**{len(user_warnings)}**", inline=True)
            
            await ctx.send(embed=embed)
            return
    
    await ctx.send("❌ Предупреждение с таким ID не найдено!")

@bot.command(name='кик')
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "Не указана"):
    """Кикнуть пользователя"""
    if member == ctx.author:
        await ctx.send("❌ Нельзя кикнуть самого себя!")
        return
    
    try:
        await member.kick(reason=f"{ctx.author}: {reason}")
        
        embed = discord.Embed(
            title="👢 **ПОЛЬЗОВАТЕЛЬ ВЫГНАН**",
            color=discord.Color.orange()
        )
        
        embed.add_field(name="👤 **Пользователь**", value=member.mention, inline=True)
        embed.add_field(name="🛡️ **Модератор**", value=ctx.author.mention, inline=True)
        embed.add_field(name="📝 **Причина**", value=reason, inline=False)
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("❌ У меня нет прав кикать этого пользователя!")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name='бан')
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Не указана"):
    """Забанить пользователя"""
    if member == ctx.author:
        await ctx.send("❌ Нельзя забанить самого себя!")
        return
    
    try:
        await member.ban(reason=f"{ctx.author}: {reason}", delete_message_days=0)
        
        embed = discord.Embed(
            title="🔨 **ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН**",
            color=discord.Color.red()
        )
        
        embed.add_field(name="👤 **Пользователь**", value=member.mention, inline=True)
        embed.add_field(name="🛡️ **Модератор**", value=ctx.author.mention, inline=True)
        embed.add_field(name="📝 **Причина**", value=reason, inline=False)
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("❌ У меня нет прав банить этого пользователя!")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name='разбан')
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: str):
    """Разбанить пользователя"""
    try:
        user_id = int(user_id)
    except ValueError:
        await ctx.send("❌ Укажите правильный ID пользователя!")
        return
    
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        
        embed = discord.Embed(
            title="✅ **ПОЛЬЗОВАТЕЛЬ РАЗБАНЕН**",
            color=discord.Color.green()
        )
        
        embed.add_field(name="👤 **Пользователь**", value=f"{user.name}#{user.discriminator}", inline=True)
        embed.add_field(name="🛡️ **Модератор**", value=ctx.author.mention, inline=True)
        
        await ctx.send(embed=embed)
        
    except discord.NotFound:
        await ctx.send("❌ Пользователь не найден или не забанен!")
    except discord.Forbidden:
        await ctx.send("❌ У меня нет прав разбанивать!")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name='мут')
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, duration: str, *, reason: str = "Не указана"):
    """Выдать мут"""
    if member == ctx.author:
        await ctx.send("❌ Нельзя замутить самого себя!")
        return
    
    # Парсим время
    time_units = {
        's': 1, 'сек': 1, 'секунд': 1,
        'm': 60, 'мин': 60, 'минут': 60,
        'h': 3600, 'ч': 3600, 'час': 3600,
        'd': 86400, 'д': 86400, 'день': 86400
    }
    
    duration_num = ''.join(filter(str.isdigit, duration))
    duration_unit = ''.join(filter(str.isalpha, duration)).lower()
    
    if not duration_num or duration_unit not in time_units:
        await ctx.send("❌ Укажите время правильно! Например: `10мин`, `1ч`, `30сек`")
        return
    
    seconds = int(duration_num) * time_units[duration_unit]
    
    if seconds > 2419200:  # Максимум 28 дней
        await ctx.send("❌ Максимальное время мута - 28 дней!")
        return
    
    try:
        timeout_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=seconds)
        await member.timeout(timeout_until, reason=f"{ctx.author}: {reason}")
        
        # Сохраняем мут
        guild_id = str(ctx.guild.id)
        mutes_data = storage.get_guild_data(guild_id, 'mutes')
        if str(member.id) not in mutes_data:
            mutes_data[str(member.id)] = []
        
        mutes_data[str(member.id)].append({
            'moderator': ctx.author.id,
            'duration': seconds,
            'reason': reason,
            'timestamp': time.time()
        })
        storage.set_guild_data(guild_id, 'mutes', mutes_data)
        
        embed = discord.Embed(
            title="🔇 **ВЫДАН МУТ**",
            color=discord.Color.dark_gray()
        )
        
        embed.add_field(name="👤 **Пользователь**", value=member.mention, inline=True)
        embed.add_field(name="🛡️ **Модератор**", value=ctx.author.mention, inline=True)
        embed.add_field(name="⏰ **Длительность**", value=duration, inline=True)
        embed.add_field(name="📝 **Причина**", value=reason, inline=False)
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("❌ У меня нет прав выдавать мут!")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name='размут')
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    """Снять мут"""
    try:
        await member.timeout(None, reason=f"Размут от {ctx.author}")
        
        embed = discord.Embed(
            title="🔊 **МУТ СНЯТ**",
            color=discord.Color.green()
        )
        
        embed.add_field(name="👤 **Пользователь**", value=member.mention, inline=True)
        embed.add_field(name="🛡️ **Модератор**", value=ctx.author.mention, inline=True)
        
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        await ctx.send("❌ У меня нет прав снимать мут!")
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name='очистить')
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 10):
    """Очистить сообщения"""
    if amount <= 0 or amount > 100:
        await ctx.send("❌ Укажите число от 1 до 100!", delete_after=5)
        return
    
    try:
        deleted = await ctx.channel.purge(limit=amount + 1)
        
        embed = discord.Embed(
            title="🧹 **ОЧИСТКА ЗАВЕРШЕНА**",
            description=f"Удалено **{len(deleted)-1}** сообщений",
            color=discord.Color.green()
        )
        
        msg = await ctx.send(embed=embed)
        
        try:
            await asyncio.sleep(3)
            await msg.delete()
        except discord.NotFound:
            pass  # Сообщение уже удалено - игнорируем ошибку
        
    except discord.Forbidden:
        await ctx.send("❌ У меня нет прав удалять сообщения!", delete_after=5)
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}", delete_after=5)

# ==================== АВТОМОДЕРАЦИЯ ====================
@bot.command(name='автомод')
@commands.has_permissions(administrator=True)
async def automod_command(ctx, action: str = None, *, args: str = None):
    """Управление автомодерацией"""
    guild_id = str(ctx.guild.id)
    auto_mod_data = storage.get_guild_data(guild_id, 'auto_mod')
    
    if not action:
        # Показать настройки
        embed = discord.Embed(
            title="⚙️ **НАСТРОЙКИ АВТОМОДЕРАЦИИ**",
            color=discord.Color.blue()
        )
        
        # Статус
        enabled = "✅ ВКЛ" if auto_mod_data.get('enabled', True) else "❌ ВЫКЛ"
        embed.add_field(name="Статус", value=enabled, inline=True)
        
        # Статистика
        logs_data = storage.get_guild_data(guild_id, 'mod_logs')
        violations_count = len(logs_data.get('violations', []))
        embed.add_field(name="🚨 Нарушений", value=str(violations_count), inline=True)
        
        # Настройки модулей
        modules = [
            ("🛡️ Анти-спам", auto_mod_data.get('anti_spam', True)),
            ("👥 Анти-упоминания", auto_mod_data.get('anti_mention', True)),
            ("🔠 Анти-капс", auto_mod_data.get('anti_caps', True)),
            ("🔗 Анти-ссылки", auto_mod_data.get('anti_links', False)),
            ("🗣️ Анти-мат", auto_mod_data.get('anti_bad_words', True)),
            ("🔁 Анти-повторы", auto_mod_data.get('anti_repeat', True)),
            ("😀 Анти-эмодзи", auto_mod_data.get('anti_emoji_spam', True)),
            ("📨 Анти-инвайты", auto_mod_data.get('anti_invites', True))
        ]
        
        for name, status in modules:
            embed.add_field(name=name, value="✅" if status else "❌", inline=True)
        
        # Параметры
        embed.add_field(
            name="📊 Параметры",
            value=f"**Спам:** {auto_mod_data.get('spam_limit', 5)} сообщений/{auto_mod_data.get('spam_time', 5)}сек\n"
                  f"**Упоминания:** {auto_mod_data.get('mention_limit', 5)} макс\n"
                  f"**Капс:** {auto_mod_data.get('caps_threshold', 0.7)*100}% порог",
            inline=False
        )
        
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action in ['вкл', 'включить']:
        auto_mod_data['enabled'] = True
        storage.set_guild_data(guild_id, 'auto_mod', auto_mod_data)
        await ctx.send("✅ Автомодерация включена!")
    
    elif action in ['выкл', 'выключить']:
        auto_mod_data['enabled'] = False
        storage.set_guild_data(guild_id, 'auto_mod', auto_mod_data)
        await ctx.send("✅ Автомодерация выключена!")
    
    elif action == 'настройки':
        # Показать детальные настройки
        embed = discord.Embed(
            title="⚙️ **ДЕТАЛЬНЫЕ НАСТРОЙКИ**",
            description="Используйте: `!автомод установить параметр значение`",
            color=discord.Color.blue()
        )
        
        settings_list = [
            ("spam_limit", "Лимит спама (сообщений)", "5"),
            ("spam_time", "Время для спама (секунд)", "5"),
            ("mention_limit", "Лимит упоминаний", "5"),
            ("caps_threshold", "Порог капса (0-1)", "0.7"),
            ("action_delete", "Удалять сообщения", "Да"),
            ("action_warn", "Отправлять предупреждения", "Да"),
            ("action_mute", "Выдавать мут", "Да"),
            ("action_kick", "Кикать при 5 предупреждениях", "Нет"),
            ("action_ban", "Банить при 5 предупреждениях", "Нет")
        ]
        
        for key, name, default in settings_list:
            value = auto_mod_data.get(key, default)
            embed.add_field(name=name, value=str(value), inline=True)
        
        await ctx.send(embed=embed)
    
    elif action == 'установить':
        if not args:
            await ctx.send("❌ Укажите параметр и значение! Пример: `!автомод установить spam_limit 10`")
            return
        
        parts = args.split()
        if len(parts) < 2:
            await ctx.send("❌ Укажите параметр и значение!")
            return
        
        param = parts[0]
        value = " ".join(parts[1:])
        
        # Парсим значение
        if value.lower() in ['да', 'yes', 'true']:
            value = True
        elif value.lower() in ['нет', 'no', 'false']:
            value = False
        elif '.' in value:
            try:
                value = float(value)
            except:
                pass
        else:
            try:
                value = int(value)
            except:
                pass
        
        # Сохраняем
        auto_mod_data[param] = value
        storage.set_guild_data(guild_id, 'auto_mod', auto_mod_data)
        
        await ctx.send(f"✅ Параметр `{param}` установлен в `{value}`")
    
    elif action == 'логи':
        # Показать логи нарушений
        logs_data = storage.get_guild_data(guild_id, 'mod_logs')
        violations = logs_data.get('violations', [])
        
        if not violations:
            await ctx.send("📭 Логи нарушений пусты")
            return
        
        embed = discord.Embed(
            title="📋 **ЛОГИ АВТОМОДЕРАЦИИ**",
            color=discord.Color.dark_grey()
        )
        
        # Показываем последние 5 нарушений
        for violation in violations[-5:]:
            timestamp = f"<t:{int(violation['timestamp'])}:R>"
            embed.add_field(
                name=f"👤 {violation['user_name']} | {timestamp}",
                value=f"**Нарушения:** {', '.join(violation['violations'])}\n"
                      f"**Предупреждение:** #{violation['warning_count']}\n"
                      f"**Сообщение:** {violation['message'][:100]}...",
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    elif action == 'сброс':
        # Сбросить предупреждения для пользователя
        if not args:
            await ctx.send("❌ Укажите пользователя! Пример: `!автомод сброс @пользователь`")
            return
        
        member = None
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
        else:
            try:
                member_id = int(args)
                member = ctx.guild.get_member(member_id)
            except:
                await ctx.send("❌ Укажите правильного пользователя!")
                return
        
        if not member:
            await ctx.send("❌ Пользователь не найден!")
            return
        
        user_id = str(member.id)
        
        # Сбрасываем предупреждения
        if guild_id in auto_mod_system.spam_warnings:
            if user_id in auto_mod_system.spam_warnings[guild_id]:
                auto_mod_system.spam_warnings[guild_id][user_id] = 0
        
        await ctx.send(f"✅ Предупреждения сброшены для {member.mention}")
    
    elif action == 'модуль':
        # Включить/выключить модуль
        if not args:
            await ctx.send("❌ Укажите модуль! Пример: `!автомод модуль anti_spam вкл`")
            return
        
        parts = args.split()
        if len(parts) < 2:
            await ctx.send("❌ Укажите модуль и действие!")
            return
        
        module = parts[0]
        module_action = parts[1].lower()
        
        modules_map = {
            'спам': 'anti_spam',
            'упоминания': 'anti_mention',
            'капс': 'anti_caps',
            'ссылки': 'anti_links',
            'мат': 'anti_bad_words',
            'повторы': 'anti_repeat',
            'эмодзи': 'anti_emoji_spam',
            'инвайты': 'anti_invites'
        }
        
        # Проверяем русские названия
        if module in modules_map:
            module = modules_map[module]
        
        if module not in ['anti_spam', 'anti_mention', 'anti_caps', 'anti_links',
                         'anti_bad_words', 'anti_repeat', 'anti_emoji_spam', 'anti_invites']:
            await ctx.send("❌ Неизвестный модуль!")
            return
        
        if module_action in ['вкл', 'включить', 'on', 'true']:
            auto_mod_data[module] = True
            status = "включен"
        else:
            auto_mod_data[module] = False
            status = "выключен"
        
        storage.set_guild_data(guild_id, 'auto_mod', auto_mod_data)
        await ctx.send(f"✅ Модуль `{module}` {status}!")

@bot.command(name='добавитьслово')
@commands.has_permissions(manage_messages=True)
async def add_bad_word(ctx, *, word: str):
    """Добавить запрещенное слово"""
    guild_id = str(ctx.guild.id)
    bad_words_data = storage.get_guild_data(guild_id, 'bad_words')
    
    if guild_id not in bad_words_data:
        bad_words_data[guild_id] = []
    
    if word.lower() in bad_words_data[guild_id]:
        await ctx.send("❌ Это слово уже в списке!")
        return
    
    bad_words_data[guild_id].append(word.lower())
    storage.set_guild_data(guild_id, 'bad_words', bad_words_data)
    
    embed = discord.Embed(
        title="✅ **СЛОВО ДОБАВЛЕНО**",
        description=f"Запрещенное слово: `{word}`",
        color=discord.Color.green()
    )
    
    await ctx.send(embed=embed)

@bot.command(name='удалитьслово')
@commands.has_permissions(manage_messages=True)
async def remove_bad_word(ctx, *, word: str):
    """Удалить запрещенное слово"""
    guild_id = str(ctx.guild.id)
    bad_words_data = storage.get_guild_data(guild_id, 'bad_words')
    
    if guild_id not in bad_words_data or word.lower() not in bad_words_data[guild_id]:
        await ctx.send("❌ Этого слова нет в списке!")
        return
    
    bad_words_data[guild_id].remove(word.lower())
    storage.set_guild_data(guild_id, 'bad_words', bad_words_data)
    
    embed = discord.Embed(
        title="✅ **СЛОВО УДАЛЕНО**",
        description=f"Удалено слово: `{word}`",
        color=discord.Color.green()
    )
    
    await ctx.send(embed=embed)

@bot.command(name='списокслов')
async def list_bad_words(ctx):
    """Показать список запрещенных слов"""
    guild_id = str(ctx.guild.id)
    bad_words_data = storage.get_guild_data(guild_id, 'bad_words')
    
    words_list = bad_words_data.get(guild_id, [])
    
    embed = discord.Embed(
        title="🚫 **ЗАПРЕЩЕННЫЕ СЛОВА**",
        color=discord.Color.red()
    )
    
    if not words_list:
        embed.description = "Список пуст. Добавьте слова командой `!добавитьслово`"
    else:
        words_text = "\n".join([f"• `{word}`" for word in words_list])
        embed.description = f"Всего слов: **{len(words_list)}**\n\n{words_text}"
    
    await ctx.send(embed=embed)

@bot.event
async def on_message(message):
    # Пропускаем сообщения в ЛС
    if not message.guild:
        return
    
    # Пропускаем сообщения бота
    if message.author.bot:
        return
    
    # Проверяем на нарушения автомодерацией
    violation_found = await auto_mod_system.check_message(message)
    
    # Если найдено нарушение, не обрабатываем дальше
    if violation_found:
        return
    
    # Старая проверка запрещенных слов (теперь в автомодерации)
    guild_id = str(message.guild.id)
    bad_words_data = storage.get_guild_data(guild_id, 'bad_words')
    
    words_list = bad_words_data.get(guild_id, [])
    if words_list:
        message_lower = message.content.lower()
        for word in words_list:
            if word in message_lower:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention}, пожалуйста, не используйте запрещенные слова!",
                        delete_after=5
                    )
                    
                    # Авто-варн
                    warnings_data = storage.get_guild_data(guild_id, 'warnings')
                    user_id = str(message.author.id)
                    
                    if user_id not in warnings_data:
                        warnings_data[user_id] = []
                    
                    warn_id = len(warnings_data[user_id]) + 1
                    warning = {
                        'id': warn_id,
                        'moderator': bot.user.id,
                        'reason': f"Использование запрещенного слова: {word}",
                        'timestamp': time.time()
                    }
                    
                    warnings_data[user_id].append(warning)
                    storage.set_guild_data(guild_id, 'warnings', warnings_data)
                    return
                except:
                    pass
    
    # Обрабатываем команды
    await bot.process_commands(message)


@bot.event
async def on_message(message):
    # Пропускаем сообщения бота
    if message.author.bot:
        return
    
    # Проверка запрещенных слов
    guild_id = str(message.guild.id)
    bad_words_data = storage.get_guild_data(guild_id, 'bad_words')
    
    words_list = bad_words_data.get(guild_id, [])
    if words_list:
        message_lower = message.content.lower()
        for word in words_list:
            if word in message_lower:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention}, пожалуйста, не используйте запрещенные слова!",
                        delete_after=5
                    )
                    
                    # Авто-варн
                    warnings_data = storage.get_guild_data(guild_id, 'warnings')
                    user_id = str(message.author.id)
                    
                    if user_id not in warnings_data:
                        warnings_data[user_id] = []
                    
                    warn_id = len(warnings_data[user_id]) + 1
                    warning = {
                        'id': warn_id,
                        'moderator': bot.user.id,
                        'reason': f"Использование запрещенного слова: {word}",
                        'timestamp': time.time()
                    }
                    
                    warnings_data[user_id].append(warning)
                    storage.set_guild_data(guild_id, 'warnings', warnings_data)
                    return
                except:
                    pass
    
    await bot.process_commands(message)

# ==================== ПРИВЕТСТВИЯ ====================
@bot.command(name='приветствие')
async def welcome_command(ctx, action: str = None, *, args: str = None):
    """Настройка приветственных сообщений"""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ Только администраторы могут настраивать приветствия!")
        return
    
    guild_id = str(ctx.guild.id)
    welcome_data = storage.get_guild_data(guild_id, 'welcome')
    
    if not action:
        # Показать настройки
        embed = discord.Embed(
            title="👋 **НАСТРОЙКИ ПРИВЕТСТВИЙ**",
            color=discord.Color.blue()
        )
        
        enabled = "✅ ВКЛ" if welcome_data.get('enabled', False) else "❌ ВЫКЛ"
        channel = f"<#{welcome_data.get('channel')}>" if welcome_data.get('channel') else "Не установлен"
        message = welcome_data.get('message', 'Добро пожаловать, {mention}!')
        
        embed.add_field(name="Статус", value=enabled, inline=True)
        embed.add_field(name="Канал", value=channel, inline=True)
        embed.add_field(name="Сообщение", value=message[:100] + "..." if len(message) > 100 else message, inline=False)
        
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action in ['вкл', 'включить']:
        welcome_data['enabled'] = True
        storage.set_guild_data(guild_id, 'welcome', welcome_data)
        await ctx.send("✅ Приветственные сообщения включены!")
    
    elif action in ['выкл', 'выключить']:
        welcome_data['enabled'] = False
        storage.set_guild_data(guild_id, 'welcome', welcome_data)
        await ctx.send("✅ Приветственные сообщения выключены!")
    
    elif action == 'канал':
        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
            welcome_data['channel'] = channel.id
            storage.set_guild_data(guild_id, 'welcome', welcome_data)
            await ctx.send(f"✅ Канал для приветствий установлен: {channel.mention}")
        else:
            await ctx.send("❌ Упомяните канал! Пример: `!приветствие канал #general`")
    
    elif action == 'сообщение':
        if args:
            welcome_data['message'] = args
            storage.set_guild_data(guild_id, 'welcome', welcome_data)
            await ctx.send(f"✅ Сообщение установлено: {args}")
        else:
            await ctx.send("❌ Укажите текст сообщения!")
    
    elif action == 'баннер':
        if args and args.startswith('http'):
            welcome_data['banner'] = args
            storage.set_guild_data(guild_id, 'welcome', welcome_data)
            await ctx.send("✅ Баннер установлен!")
        else:
            await ctx.send("❌ Укажите валидную ссылку на изображение!")
    
    elif action == 'правило':
        # Простой переключатель правил
        show_rules = welcome_data.get('show_rules', False)
        welcome_data['show_rules'] = not show_rules
        storage.set_guild_data(guild_id, 'welcome', welcome_data)
        status = "включены" if not show_rules else "выключены"
        await ctx.send(f"✅ Правила {status} в приветствии!")
    
    elif action == 'сброс':
        storage.set_guild_data(guild_id, 'welcome', {})
        await ctx.send("✅ Настройки приветствий сброшены!")

@bot.event
async def on_member_join(member):
    guild_id = str(member.guild.id)
    welcome_data = storage.get_guild_data(guild_id, 'welcome')
    
    if not welcome_data.get('enabled', False):
        return
    
    channel_id = welcome_data.get('channel')
    if not channel_id:
        return
    
    channel = member.guild.get_channel(channel_id)
    if not channel:
        return
    
    message = welcome_data.get('message', 'Добро пожаловать, {mention}!')
    message = message.replace('{mention}', member.mention)
    message = message.replace('{name}', member.name)
    message = message.replace('{server}', member.guild.name)
    
    embed = discord.Embed(
        title=f"👋 Добро пожаловать на {member.guild.name}!",
        description=message,
        color=discord.Color.green()
    )
    
    if welcome_data.get('banner'):
        embed.set_image(url=welcome_data['banner'])
    
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.add_field(name="Участник №", value=f"#{member.guild.member_count}", inline=True)
    
    if welcome_data.get('show_rules', False):
        embed.add_field(name="📜 Правила", value="Ознакомьтесь с правилами сервера!", inline=True)
    
    await channel.send(embed=embed)

# ==================== ИГРЫ ====================
@bot.command(name='угадай')
@commands.cooldown(1, 30, commands.BucketType.user)
async def guess_game(ctx):
    """Угадай число от 1 до 100"""
    number = random.randint(1, 100)
    attempts = 6
    
    embed = discord.Embed(
        title="🎯 **УГАДАЙ ЧИСЛО**",
        description="Я загадал число от **1 до 100**!\nУ тебя **6** попыток.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)
    
    for attempt in range(1, attempts + 1):
        try:
            msg = await bot.wait_for(
                'message',
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit(),
                timeout=30.0
            )
            
            guess = int(msg.content)
            
            if guess < 1 or guess > 100:
                await ctx.send("❌ Число должно быть от 1 до 100!", delete_after=2)
                continue
            
            if guess < number:
                await ctx.send(f"🔼 **Больше чем {guess}** (Попытка {attempt}/6)")
            elif guess > number:
                await ctx.send(f"🔽 **Меньше чем {guess}** (Попытка {attempt}/6)")
            else:
                # Победа
                reward = {1: 500, 2: 400, 3: 300, 4: 200, 5: 150, 6: 100}[attempt]
                
                guild_id = str(ctx.guild.id)
                user_id = str(ctx.author.id)
                economy_data = storage.get_guild_data(guild_id, 'economy')
                economy_data[user_id] = economy_data.get(user_id, 0) + reward
                storage.set_guild_data(guild_id, 'economy', economy_data)
                
                win_embed = discord.Embed(
                    title="🎉 **ПОБЕДА!**",
                    description=f"Ты угадал число **{number}** за **{attempt}** попыток!",
                    color=discord.Color.green()
                )
                win_embed.add_field(name="💰 Награда", value=f"**{reward}** кредитов")
                await ctx.send(embed=win_embed)
                return
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ Время вышло!")
            return
    
    # Проигрыш
    lose_embed = discord.Embed(
        title="💀 **ПОРАЖЕНИЕ**",
        description=f"Число было: **{number}**",
        color=discord.Color.red()
    )
    await ctx.send(embed=lose_embed)

@bot.command(name='slots')
@commands.cooldown(1, 5, commands.BucketType.user)
async def slots(ctx, bet: int = 10):
    """Игровой автомат"""
    if bet < 10:
        await ctx.send("❌ Минимальная ставка - 10 кредитов!")
        return
    
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    economy_data = storage.get_guild_data(guild_id, 'economy')
    balance = economy_data.get(user_id, 0)
    
    if balance < bet:
        await ctx.send(f"❌ Недостаточно кредитов! У тебя: {balance}")
        return
    
    symbols = ['🍒', '🍋', '🍊', '🍉', '🍇', '⭐', '7️⃣', '🔔', '💎']
    result = [random.choice(symbols) for _ in range(3)]
    
    # Проверка выигрыша
    if result[0] == result[1] == result[2]:
        if result[0] == '7️⃣':
            multiplier = 100
        elif result[0] == '💎':
            multiplier = 50
        elif result[0] == '⭐':
            multiplier = 30
        else:
            multiplier = 10
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
        multiplier = 3
    elif all(s in ['🍒', '🍋', '🍊', '🍉', '🍇'] for s in result):
        multiplier = 5
    else:
        multiplier = 0
    
    winnings = bet * multiplier - bet if multiplier > 0 else -bet
    economy_data[user_id] = balance + winnings
    storage.set_guild_data(guild_id, 'economy', economy_data)
    
    embed = discord.Embed(
        title="🎰 **ИГРОВОЙ АВТОМАТ**",
        color=discord.Color.green() if winnings > 0 else discord.Color.red()
    )
    
    embed.add_field(name="🎯 Результат", value=f"**[ {result[0]} | {result[1]} | {result[2]} ]**", inline=False)
    embed.add_field(name="💰 Ставка", value=f"**{bet}** кредитов", inline=True)
    embed.add_field(name="🎁 Коэффициент", value=f"**x{multiplier if multiplier > 0 else 0}**", inline=True)
    embed.add_field(name="💸 Выигрыш", value=f"**{winnings if winnings > 0 else winnings}** кредитов", inline=True)
    embed.add_field(name="💳 Баланс", value=f"**{balance} → {balance + winnings}**", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='купитьвместе')
async def buy_together(ctx, item: str, amount: int = 1):
    """Купить что-то из общего бюджета"""
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    # Ищем брак
    marriages = storage.get_guild_data(guild_id, 'marriages')
    
    marriage_data = None
    for data in marriages.get(guild_id, {}).values():
        if data['husband'] == user_id or data['wife'] == user_id:
            marriage_data = data
            marriage_id = next(k for k, v in marriages[guild_id].items() if v == data)
            break
    
    if not marriage_data:
        await ctx.send("❌ Ты не состоишь в браке!")
        return
    
    # Стоимость покупки
    prices = {
        'пицца': 50,
        'цветы': 30,
        'кольцо': 200,
        'путешествие': 500,
        'дом': 1000,
        'машина': 800
    }
    
    item_lower = item.lower()
    if item_lower not in prices:
        items_list = "\n".join([f"• {name} - {price} кредитов" for name, price in prices.items()])
        await ctx.send(f"❌ Такого товара нет! Доступно:\n{items_list}")
        return
    
    total_cost = prices[item_lower] * amount
    
    if marriage_data.get('money_pool', 0) < total_cost:
        await ctx.send(f"❌ Недостаточно в общем бюджете! Нужно: {total_cost}, есть: {marriage_data.get('money_pool', 0)}")
        return
    
    # Совершаем покупку
    marriage_data['money_pool'] = marriage_data.get('money_pool', 0) - total_cost
    
    # Находим второго участника
    partner_id = marriage_data['wife'] if marriage_data['husband'] == user_id else marriage_data['husband']
    partner = ctx.guild.get_member(int(partner_id))
    
    # Сохраняем
    marriages[guild_id][marriage_id] = marriage_data
    storage.set_guild_data(guild_id, 'marriages', marriages)
    
    # Реакции в зависимости от покупки
    reactions = {
        'пицца': "🍕",
        'цветы': "💐",
        'кольцо': "💍",
        'путешествие': "✈️",
        'дом': "🏠",
        'машина': "🚗"
    }
    
    embed = discord.Embed(
        title=f"{reactions.get(item_lower, '🛒')} **СОВМЕСТНАЯ ПОКУПКА**",
        description=f"{ctx.author.mention} и {partner.mention if partner else 'супруг(а)'} купили {item} за {total_cost} кредитов!",
        color=discord.Color.green()
    )
    embed.add_field(name="💰 Осталось в бюджете", value=f"**{marriage_data['money_pool']}** кредитов", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='подарок')
async def gift(ctx, member: discord.Member, amount: int):
    """Подарить кредиты супругу/супруге"""
    if amount <= 0:
        await ctx.send("❌ Укажите положительное число!")
        return
    
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    target_id = str(member.id)
    
    # Проверяем что это супруг/супруга
    marriages = storage.get_guild_data(guild_id, 'marriages')
    
    is_spouse = False
    for data in marriages.get(guild_id, {}).values():
        if (data['husband'] == user_id and data['wife'] == target_id) or \
           (data['wife'] == user_id and data['husband'] == target_id):
            is_spouse = True
            marriage_data = data
            marriage_id = next(k for k, v in marriages[guild_id].items() if v == data)
            break
    
    if not is_spouse:
        await ctx.send("❌ Можно дарить подарки только супругу/супруге!")
        return
    
    # Проверяем баланс
    economy_data = storage.get_guild_data(guild_id, 'economy')
    author_balance = economy_data.get(user_id, 0)
    
    if author_balance < amount:
        await ctx.send(f"❌ Недостаточно кредитов! У тебя: {author_balance}")
        return
    
    # Переводим в общий бюджет
    economy_data[user_id] = author_balance - amount
    marriage_data['money_pool'] = marriage_data.get('money_pool', 0) + amount
    
    # Сохраняем
    marriages[guild_id][marriage_id] = marriage_data
    storage.set_guild_data(guild_id, 'marriages', marriages)
    storage.set_guild_data(guild_id, 'economy', economy_data)
    
    embed = discord.Embed(
        title="🎁 **ПОДАРОК ПРИНЯТ!**",
        description=f"{ctx.author.mention} подарил(а) {member.mention} {amount} кредитов в общий бюджет!",
        color=discord.Color.pink()
    )
    embed.add_field(name="💰 Общий бюджет", value=f"Теперь: **{marriage_data['money_pool']}** кредитов", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='развод')
async def divorce(ctx):
    """Подать на развод"""
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    marriages = storage.get_guild_data(guild_id, 'marriages')
    
    # Ищем брак
    marriage_data = None
    marriage_id = None
    
    for mid, data in marriages.get(guild_id, {}).items():
        if data['husband'] == user_id or data['wife'] == user_id:
            marriage_data = data
            marriage_id = mid
            break
    
    if not marriage_data:
        await ctx.send("❌ Ты не состоишь в браке!")
        return
    
    # Проверяем не подал ли уже второй участник
    if marriage_data.get('divorce_requested'):
        # Второй участник уже подал - разводим
        partner_id = marriage_data['wife'] if marriage_data['husband'] == user_id else marriage_data['husband']
        partner = ctx.guild.get_member(int(partner_id))
        
        # Делим деньги
        money_pool = marriage_data.get('money_pool', 0)
        half = money_pool // 2
        
        economy_data = storage.get_guild_data(guild_id, 'economy')
        economy_data[user_id] = economy_data.get(user_id, 0) + half
        economy_data[partner_id] = economy_data.get(partner_id, 0) + half
        
        # Удаляем брак
        del marriages[guild_id][marriage_id]
        
        storage.set_guild_data(guild_id, 'marriages', marriages)
        storage.set_guild_data(guild_id, 'economy', economy_data)
        
        embed = discord.Embed(
            title="💔 **РАЗВОД ОФОРМЛЕН**",
            description=f"Брак между {ctx.author.mention} и {partner.mention if partner else 'неизвестным'} расторгнут.",
            color=discord.Color.dark_grey()
        )
        if money_pool > 0:
            embed.add_field(name="💰 Раздел имущества", value=f"Каждому по {half} кредитов", inline=True)
        
        await ctx.send(embed=embed)
        
    else:
        # Первый запрос на развод
        marriages[guild_id][marriage_id]['divorce_requested'] = True
        storage.set_guild_data(guild_id, 'marriages', marriages)
        
        partner_id = marriage_data['wife'] if marriage_data['husband'] == user_id else marriage_data['husband']
        partner = ctx.guild.get_member(int(partner_id))
        
        embed = discord.Embed(
            title="⚠️ **ЗАПРОС НА РАЗВОД**",
            description=f"{ctx.author.mention} подал(а) на развод с {partner.mention if partner else 'неизвестным'}",
            color=discord.Color.orange()
        )
        embed.add_field(name="📝 Для подтверждения", value="Второй участник должен тоже ввести `!развод`", inline=False)
        embed.add_field(name="⏳ Истекает", value="Через 7 дней", inline=True)
        
        await ctx.send(embed=embed)

@bot.command(name='брак')
async def marriage_info(ctx, member: discord.Member = None):
    """Информация о браке"""
    member = member or ctx.author
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    marriages = storage.get_guild_data(guild_id, 'marriages')
    
    # Ищем брак где участвует этот пользователь
    marriage_data = None
    marriage_id = None
    
    for mid, data in marriages.get(guild_id, {}).items():
        if data['husband'] == user_id or data['wife'] == user_id:
            marriage_data = data
            marriage_id = mid
            break
    
    if not marriage_data:
        if member == ctx.author:
            await ctx.send("💔 Ты не состоишь в браке!")
        else:
            await ctx.send(f"💔 {member.mention} не состоит в браке!")
        return
    
    # Находим второго участника
    partner_id = marriage_data['wife'] if marriage_data['husband'] == user_id else marriage_data['husband']
    partner = ctx.guild.get_member(int(partner_id))
    
    # Вычисляем сколько дней вместе
    days_together = int((time.time() - marriage_data['married_at']) / 86400)
    
    embed = discord.Embed(
        title="💍 **ИНФОРМАЦИЯ О БРАКЕ**",
        color=discord.Color.pink()
    )
    
    embed.add_field(name="👰 Невеста" if marriage_data['wife'] == user_id else "🤵 Жених", 
                   value=member.mention, inline=True)
    embed.add_field(name="🤵 Жених" if marriage_data['husband'] == partner_id else "👰 Невеста", 
                   value=partner.mention if partner else "Неизвестно", inline=True)
    
    embed.add_field(name="💒 Дата брака", 
                   value=f"<t:{int(marriage_data['married_at'])}:D>", inline=True)
    embed.add_field(name="📅 Дней вместе", 
                   value=f"**{days_together}** дней", inline=True)
    
    if marriage_data['money_pool'] > 0:
        embed.add_field(name="💰 Общий бюджет", 
                       value=f"**{marriage_data['money_pool']}** кредитов", inline=True)
    
    # Вычисляем "уровень любви" (шуточный)
    love_level = min(100, days_together * 5)
    love_bar = "❤️" * (love_level // 20) + "🤍" * (5 - love_level // 20)
    
    embed.add_field(name="💖 Уровень любви", 
                   value=f"{love_bar} {love_level}%", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='отказать')
async def reject_proposal(ctx):
    """Отказать от предложения брака"""
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    proposals = storage.get_guild_data(guild_id, 'marriage_proposals')
    
    # Ищем предложение для этого пользователя
    proposer_id = None
    for pid, data in proposals.get(guild_id, {}).items():
        if data['to'] == user_id:
            proposer_id = pid
            break
    
    if not proposer_id:
        await ctx.send("❌ У тебя нет активных предложений брака!")
        return
    
    # Находим предложившего
    proposer = ctx.guild.get_member(int(proposer_id))
    
    # Возвращаем 50% денег
    economy_data = storage.get_guild_data(guild_id, 'economy')
    refund = 50  # 50 из 100
    economy_data[proposer_id] = economy_data.get(proposer_id, 0) + refund
    
    # Удаляем предложение
    del proposals[guild_id][proposer_id]
    
    # Сохраняем
    storage.set_guild_data(guild_id, 'marriage_proposals', proposals)
    storage.set_guild_data(guild_id, 'economy', economy_data)
    
    embed = discord.Embed(
        title="🚫 **ПРЕДЛОЖЕНИЕ ОТКЛОНЕНО**",
        description=f"{ctx.author.mention} отказал(а) {proposer.mention if proposer else 'неизвестному'}",
        color=discord.Color.dark_grey()
    )
    embed.add_field(name="💰 Возвращено", value=f"{refund} кредитов", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='принять')
async def accept_proposal(ctx):
    """Принять предложение брака"""
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    proposals = storage.get_guild_data(guild_id, 'marriage_proposals')
    marriages = storage.get_guild_data(guild_id, 'marriages')
    
    # Ищем предложение для этого пользователя
    proposer_id = None
    for pid, data in proposals.get(guild_id, {}).items():
        if data['to'] == user_id:
            proposer_id = pid
            break
    
    if not proposer_id:
        await ctx.send("❌ У тебя нет активных предложений брака!")
        return
    
    proposal_data = proposals[guild_id][proposer_id]
    
    # Проверяем не прошло ли 24 часа
    if time.time() - proposal_data['timestamp'] > 86400:
        await ctx.send("❌ Предложение брака истекло! (24 часа)")
        del proposals[guild_id][proposer_id]
        storage.set_guild_data(guild_id, 'marriage_proposals', proposals)
        return
    
    # Создаём брак
    if guild_id not in marriages:
        marriages[guild_id] = {}
    
    marriage_id = f"{proposer_id}_{user_id}"
    marriages[guild_id][marriage_id] = {
        'husband': proposer_id,
        'wife': user_id,
        'married_at': time.time(),
        'divorced': False,
        'money_pool': 0
    }
    
    # Удаляем предложение
    del proposals[guild_id][proposer_id]
    
    # Сохраняем
    storage.set_guild_data(guild_id, 'marriages', marriages)
    storage.set_guild_data(guild_id, 'marriage_proposals', proposals)
    
    # Находим участников
    proposer = ctx.guild.get_member(int(proposer_id))
    
    # Создаём роль для пары (если есть права)
    try:
        # Пробуем создать роль
        color = discord.Color.pink()
        role = await ctx.guild.create_role(
            name=f"💍 {proposer.name} & {ctx.author.name}",
            color=color,
            reason="Брачная церемония"
        )
        
        # Выдаём роли участникам
        if proposer:
            await proposer.add_roles(role)
        await ctx.author.add_roles(role)
        
        role_msg = f"\n\n👑 **Создана брачная роль:** {role.mention}"
    except:
        role_msg = "\n\n⚠️ *Не удалось создать роль (нужны права)*"
    
    # Отправляем поздравления
    embed = discord.Embed(
        title="🎉 **ПОЗДРАВЛЯЕМ С БРАКОМ!**",
        description=f"**{proposer.mention if proposer else 'Неизвестный'}** ❤️ **{ctx.author.mention}**",
        color=discord.Color.pink()
    )
    embed.add_field(name="💒 Дата брака", value=f"<t:{int(time.time())}:D>", inline=True)
    embed.add_field(name="💍 ID пары", value=f"`{marriage_id}`", inline=True)
    
    if role_msg:
        embed.add_field(name="💝 Особое", value=role_msg, inline=False)
    
    embed.set_footer(text="Используйте !брак для информации о браке")
    
    await ctx.send(embed=embed)
    
    # Отправляем подарок - 500 кредитов в общий бюджет
    economy_data = storage.get_guild_data(guild_id, 'economy')
    marriages[guild_id][marriage_id]['money_pool'] = 500
    
    # Дарим подарки обоим
    for pid in [proposer_id, user_id]:
        economy_data[pid] = economy_data.get(pid, 0) + 250
    
    storage.set_guild_data(guild_id, 'economy', economy_data)
    storage.set_guild_data(guild_id, 'marriages', marriages)

@bot.command(name='предложить')
async def propose(ctx, member: discord.Member):
    """Предложить брак другому пользователю"""
    if member == ctx.author:
        await ctx.send("❌ Нельзя жениться на самом себе!")
        return
    
    if member.bot:
        await ctx.send("❌ Нельзя жениться на боте! она стесняется)")
        return
    
    guild_id = str(ctx.guild.id)
    author_id = str(ctx.author.id)
    target_id = str(member.id)
    
    # Проверяем уже женат ли кто-то
    marriages = storage.get_guild_data(guild_id, 'marriages')
    
    for couple in marriages.values():
        if author_id in couple or target_id in couple:
            await ctx.send("❌ Кто-то из вас уже состоит в браке!")
            return
    
    # Проверяем уже есть ли предложение
    proposals = storage.get_guild_data(guild_id, 'marriage_proposals')
    
    if author_id in proposals:
        await ctx.send("❌ У тебя уже есть активное предложение!")
        return
    
    # Стоимость предложения - 100 кредитов
    economy_data = storage.get_guild_data(guild_id, 'economy')
    author_balance = economy_data.get(author_id, 0)
    
    if author_balance < 100:
        await ctx.send(f"❌ Нужно 100 кредитов для предложения! У тебя: {author_balance}")
        return
    
    # Снимаем деньги
    economy_data[author_id] = author_balance - 100
    storage.set_guild_data(guild_id, 'economy', economy_data)
    
    # Сохраняем предложение
    if guild_id not in proposals:
        proposals[guild_id] = {}
    
    proposals[guild_id][author_id] = {
        'to': target_id,
        'timestamp': time.time(),
        'price_paid': 100
    }
    storage.set_guild_data(guild_id, 'marriage_proposals', proposals)
    
    # Отправляем предложение
    embed = discord.Embed(
        title="💍 **ПРЕДЛОЖЕНИЕ БРАКА**",
        description=f"{ctx.author.mention} предлагает брак {member.mention}!",
        color=discord.Color.pink()
    )
    embed.add_field(name="💰 Стоимость", value="100 кредитов", inline=True)
    embed.add_field(name="⏳ Действительно", value="24 часа", inline=True)
    embed.add_field(name="🤵 Жених", value=ctx.author.mention, inline=False)
    embed.add_field(name="👰 Невеста", value=member.mention, inline=False)
    embed.set_footer(text="Для ответа используйте !принять или !отказать")
    
    await ctx.send(embed=embed)
    
    # Отправляем в ЛС
    try:
        dm_embed = discord.Embed(
            title="💌 **ТЕБЕ ПРЕДЛОЖЕНИЕ!**",
            description=f"{ctx.author.name} предлагает тебе брак на сервере {ctx.guild.name}!",
            color=discord.Color.pink()
        )
        dm_embed.add_field(name="💍 Принять", value="Напиши `!принять` в том же канале", inline=True)
        dm_embed.add_field(name="🚫 Отказать", value="Напиши `!отказать` в том же канале", inline=True)
        await member.send(embed=dm_embed)
    except:
        pass

@bot.command(name='шар')
async def ball(ctx, *, question: str = None):
    """Магический шар предсказаний"""
    if question is None or question.strip() == "":
        await ctx.send("❌ Задайте вопрос! Пример: `!шар стоит ли мне учить Python?`")
        return
    
    answers = [
        "Бесспорно", "Предрешено", "Никаких сомнений", "Определённо да",
        "Можешь быть уверен в этом", "Мне кажется — да", "Вероятнее всего",
        "Хорошие перспективы", "Знаки говорят — да", "Да",
        "Пока не ясно, попробуй снова", "Спроси позже", "Лучше не рассказывать",
        "Сейчас нельзя предсказать", "Сконцентрируйся и спроси опять",
        "Даже не думай", "Мой ответ — нет", "По моим данным — нет",
        "Перспективы не очень", "Весьма сомнительно"
    ]
    answer = random.choice(answers)
    
    embed = discord.Embed(
        title="🎱 **МАГИЧЕСКИЙ ШАР**",
        color=discord.Color.purple()
    )
    embed.add_field(name="❓ Вопрос", value=question, inline=False)
    embed.add_field(name="✨ Ответ", value=answer, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='монетка')
async def coinflip(ctx):
    """Подбросить монетку"""
    result = random.choice(["Орёл", "Решка"])
    await ctx.send(f"🪙 **Монетка подброшена!** Выпало: **{result}**")

@bot.command(name='рандом')
async def random_cmd(ctx, min_num: int = 1, max_num: int = 100):
    """Случайное число""" 
    num = random.randint(min_num, max_num)
    await ctx.send(f"🎲 **Случайное число от {min_num} до {max_num}:** `{num}`")

@bot.command(name='виселица') 
@commands.cooldown(1, 30, commands.BucketType.user)
async def hangman(ctx):
    """Игра в виселицу"""
    words = ['питон', 'дискорд', 'бота', 'программирование', 'игра', 'модерация', 'команда', 'разработка']
    word = random.choice(words).upper()
    hidden = ['_' for _ in word]
    attempts = 6
    guessed = []
    
    stages = [
        """
           -----
           |   |
               |
               |
               |
               |
        =========
        """,
        """
           -----
           |   |
           O   |
               |
               |
               |
        =========
        """,
        """
           -----
           |   |
           O   |
           |   |
               |
               |
        =========
        """,
        """
           -----
           |   |
           O   |
          /|   |
               |
               |
        =========
        """,
        """
           -----
           |   |
           O   |
          /|\\  |
               |
               |
        =========
        """,
        """
           -----
           |   |
           O   |
          /|\\  |
          /    |
               |
        =========
        """,
        """
           -----
           |   |
           O   |
          /|\\  |
          / \\  |
               |
        =========
        """
    ]
    
    embed = discord.Embed(
        title="🎯 **ВИСЕЛИЦА**",
        description=f"Слово: `{' '.join(hidden)}`\n\n{stages[0]}",
        color=discord.Color.blue()
    )
    embed.add_field(name="📝 Правила", value="Отправляй по одной букве. Ошибок: 0/6")
    msg = await ctx.send(embed=embed)
    
    while attempts > 0 and '_' in hidden:
        try:
            guess_msg = await bot.wait_for(
                'message',
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel and len(m.content) == 1 and m.content.isalpha(),
                timeout=60.0
            )
            
            guess = guess_msg.content.upper()
            
            if guess in guessed:
                continue
            
            guessed.append(guess)
            
            if guess in word:
                for i, letter in enumerate(word):
                    if letter == guess:
                        hidden[i] = guess
            else:
                attempts -= 1
            
            embed = discord.Embed(
                title="🎯 **ВИСЕЛИЦА**",
                description=f"Слово: `{' '.join(hidden)}`\n\n{stages[6 - attempts]}",
                color=discord.Color.red() if attempts < 3 else discord.Color.blue()
            )
            embed.add_field(name="📝 Статус", value=f"Ошибок: {6 - attempts}/6\nИспользовано: {', '.join(guessed) if guessed else 'Нет'}")
            await msg.edit(embed=embed)
            
        except asyncio.TimeoutError:
            await ctx.send("⏰ Время вышло!")
            return
    
    if '_' not in hidden:
        reward = 100
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        economy_data = storage.get_guild_data(guild_id, 'economy')
        economy_data[user_id] = economy_data.get(user_id, 0) + reward
        
        win_embed = discord.Embed(
            title="🎉 **ПОБЕДА!**",
            description=f"Слово: **{word}**\nНаграда: **{reward}** кредитов",
            color=discord.Color.green()
        )
        await ctx.send(embed=win_embed)
    else:
        lose_embed = discord.Embed(
            title="💀 **ПОРАЖЕНИЕ**",
            description=f"Слово было: **{word}**",
            color=discord.Color.red()
        )
        await ctx.send(embed=lose_embed)

# ==================== СИСТЕМА АВТО-ЛС ====================
@bot.command(name='автолс')
@commands.has_permissions(administrator=True)
async def auto_dm_command(ctx, action: str = None, *, args: str = None):
    """Настройка авто-ЛС сообщений"""
    guild_id = str(ctx.guild.id)
    auto_dm_data = storage.get_guild_data(guild_id, 'auto_dm')
    
    if not action:
        # Показать текущие настройки
        embed = discord.Embed(
            title="📨 **НАСТРОЙКИ АВТО-ЛИЧНЫХ СООБЩЕНИЙ**",
            color=discord.Color.blue()
        )
        
        enabled = "✅ ВКЛ" if auto_dm_data.get('enabled', False) else "❌ ВЫКЛ"
        embed.add_field(name="Статус", value=enabled, inline=True)
        embed.add_field(name="📊 Отправлено", value=f"**{auto_dm_data.get('sent_count', 0)}** сообщений", inline=True)
        
        message = auto_dm_data.get('message', "Добро пожаловать на сервер {server_name}!")
        embed.add_field(name="📝 Сообщение", value=message[:200] + "..." if len(message) > 200 else message, inline=False)
        
        # Доступные переменные
        variables = "`{user}` - Имя пользователя\n`{user_mention}` - Упоминание\n`{server_name}` - Название сервера\n`{server_id}` - ID сервера\n`{member_count}` - Количество участников\n`{join_date}` - Дата присоединения"
        embed.add_field(name="🔤 Доступные переменные", value=variables, inline=False)
        
        embed.set_footer(text="Используйте !автолс вкл/выкл для управления")
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action in ['вкл', 'включить']:
        auto_dm_data['enabled'] = True
        storage.set_guild_data(guild_id, 'auto_dm', auto_dm_data)
        
        embed = discord.Embed(
            title="✅ **АВТО-ЛС ВКЛЮЧЕНЫ**",
            description="Теперь новые участники будут получать ЛС при входе на сервер",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    
    elif action in ['выкл', 'выключить']:
        auto_dm_data['enabled'] = False
        storage.set_guild_data(guild_id, 'auto_dm', auto_dm_data)
        
        embed = discord.Embed(
            title="✅ **АВТО-ЛС ВЫКЛЮЧЕНЫ**",
            description="Новые участники больше не будут получать ЛС",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
    
    elif action == 'сообщение':
        if not args:
            await ctx.send("❌ Укажите текст сообщения! Пример: `!автолс сообщение Добро пожаловать, {user}!`")
            return
        
        auto_dm_data['message'] = args
        storage.set_guild_data(guild_id, 'auto_dm', auto_dm_data)
        
        # Показываем предпросмотр
        preview = args.replace('{user}', ctx.author.name)
        preview = preview.replace('{user_mention}', ctx.author.mention)
        preview = preview.replace('{server_name}', ctx.guild.name)
        preview = preview.replace('{server_id}', str(ctx.guild.id))
        preview = preview.replace('{member_count}', str(ctx.guild.member_count))
        preview = preview.replace('{join_date}', datetime.datetime.now().strftime("%d.%m.%Y"))
        
        embed = discord.Embed(
            title="✅ **СООБЩЕНИЕ УСТАНОВЛЕНО**",
            color=discord.Color.green()
        )
        embed.add_field(name="📝 Текст сообщения", value=args, inline=False)
        embed.add_field(name="👀 Предпросмотр", value=preview, inline=False)
        
        await ctx.send(embed=embed)
    
    elif action == 'тест':
        # Тестовая отправка себе
        try:
            if not auto_dm_data.get('message'):
                await ctx.send("❌ Сначала установите сообщение командой `!автолс сообщение ваш текст`")
                return
            
            message = auto_dm_data['message']
            formatted = await format_dm_message(message, ctx.author, ctx.guild)
            
            test_embed = discord.Embed(
                title="📨 **ТЕСТОВОЕ СООБЩЕНИЕ**",
                description=formatted,
                color=discord.Color.blue()
            )
            test_embed.set_footer(text=f"Сервер: {ctx.guild.name}")
            
            await ctx.author.send(embed=test_embed)
            
            success_embed = discord.Embed(
                title="✅ **ТЕСТ УСПЕШЕН**",
                description="Тестовое сообщение отправлено вам в ЛС!",
                color=discord.Color.green()
            )
            await ctx.send(embed=success_embed)
            
        except discord.Forbidden:
            await ctx.send("❌ Не удалось отправить ЛС. Убедитесь, что у вас открыты ЛС от участников сервера!")
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {e}")
    
    elif action == 'сброс':
        storage.set_guild_data(guild_id, 'auto_dm', {})
        await ctx.send("✅ Настройки авто-ЛС сброшены!")
    
    elif action == 'статистика':
        embed = discord.Embed(
            title="📊 **СТАТИСТИКА АВТО-ЛС**",
            color=discord.Color.gold()
        )
        
        sent = auto_dm_data.get('sent_count', 0)
        failed = auto_dm_data.get('failed_count', 0)
        
        embed.add_field(name="✅ Успешно отправлено", value=f"**{sent}** сообщений", inline=True)
        embed.add_field(name="❌ Не удалось отправить", value=f"**{failed}** сообщений", inline=True)
        
        if sent > 0:
            success_rate = (sent / (sent + failed)) * 100
            embed.add_field(name="📈 Успешность", value=f"**{success_rate:.1f}%**", inline=True)
        
        last_sent = auto_dm_data.get('last_sent')
        if last_sent:
            embed.add_field(name="🕐 Последняя отправка", value=f"<t:{int(last_sent)}:R>", inline=True)
        
        await ctx.send(embed=embed)
    
    else:
        await ctx.send("❌ Неизвестная команда. Используйте: вкл, выкл, сообщение, тест, статистика, сброс")

async def format_dm_message(template: str, member: discord.Member, guild: discord.Guild) -> str:
    """Форматирует сообщение с переменными"""
    formatted = template
    
    # Заменяем все переменные
    replacements = {
        '{user}': member.name,
        '{user_mention}': member.mention,
        '{user_id}': str(member.id),
        '{server_name}': guild.name,
        '{server_id}': str(guild.id),
        '{member_count}': str(guild.member_count),
        '{join_date}': member.joined_at.strftime("%d.%m.%Y") if member.joined_at else "Неизвестно",
        '{join_time}': f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Неизвестно",
        '{created_date}': member.created_at.strftime("%d.%m.%Y") if member.created_at else "Неизвестно",
        '{created_time}': f"<t:{int(member.created_at.timestamp())}:R>" if member.created_at else "Неизвестно",
        '{bot_name}': bot.user.name,
        '{bot_mention}': bot.user.mention,
        '{date}': datetime.datetime.now().strftime("%d.%m.%Y"),
        '{time}': datetime.datetime.now().strftime("%H:%M"),
        '{timestamp}': f"<t:{int(time.time())}:R>"
    }
    
    for key, value in replacements.items():
        formatted = formatted.replace(key, value)
    
    return formatted

@bot.event
async def on_member_join(member):
    """Отправка авто-ЛС при входе на сервер"""
    guild_id = str(member.guild.id)
    auto_dm_data = storage.get_guild_data(guild_id, 'auto_dm')
    
    if not auto_dm_data.get('enabled', False):
        return
    
    if not auto_dm_data.get('message'):
        return
    
    try:
        # Форматируем сообщение
        message = auto_dm_data['message']
        formatted = await format_dm_message(message, member, member.guild)
        
        # Создаем embed
        embed = discord.Embed(
            title=f"👋 Добро пожаловать на {member.guild.name}!",
            description=formatted,
            color=discord.Color.green()
        )
        
        # Добавляем информацию о сервере
        embed.add_field(name="🏰 Сервер", value=member.guild.name, inline=True)
        embed.add_field(name="👥 Участник №", value=f"#{member.guild.member_count}", inline=True)
        
        # Устанавливаем миниатюру сервера
        if member.guild.icon:
            embed.set_thumbnail(url=member.guild.icon.url)
        
        embed.set_footer(text=f"ID: {member.guild.id} | {bot.user.name}")
        
        # Отправляем сообщение
        await member.send(embed=embed)
        
        # Обновляем статистику
        auto_dm_data['sent_count'] = auto_dm_data.get('sent_count', 0) + 1
        auto_dm_data['last_sent'] = time.time()
        storage.set_guild_data(guild_id, 'auto_dm', auto_dm_data)
        
        # Логируем в консоль
        print(f"📨 Отправлено авто-ЛС для {member.name} на сервере {member.guild.name}")
        
    except discord.Forbidden:
        # Пользователь закрыл ЛС
        auto_dm_data['failed_count'] = auto_dm_data.get('failed_count', 0) + 1
        storage.set_guild_data(guild_id, 'auto_dm', auto_dm_data)
        
        print(f"❌ Не удалось отправить авто-ЛС для {member.name} (закрытые ЛС)")
    except Exception as e:
        auto_dm_data['failed_count'] = auto_dm_data.get('failed_count', 0) + 1
        storage.set_guild_data(guild_id, 'auto_dm', auto_dm_data)
        
        print(f"❌ Ошибка отправки авто-ЛС для {member.name}: {e}")

# ==================== РАСШИРЕННЫЕ КОМАНДЫ ЛС ====================
@bot.command(name='отправить')
@commands.has_permissions(administrator=True)
async def send_dm(ctx, member: discord.Member, *, message: str = None):
    """Отправить личное сообщение пользователю от имени бота"""
    guild_id = str(ctx.guild.id)
    auto_dm_data = storage.get_guild_data(guild_id, 'auto_dm')
    
    if not message:
        # Если сообщение не указано, используем авто-ЛС шаблон
        if not auto_dm_data.get('message'):
            await ctx.send("❌ Укажите сообщение или установите авто-ЛС шаблон!")
            return
        message = auto_dm_data['message']
    
    try:
        # Форматируем сообщение
        formatted = await format_dm_message(message, member, ctx.guild)
        
        embed = discord.Embed(
            title=f"📨 **СООБЩЕНИЕ ОТ {ctx.guild.name}**",
            description=formatted,
            color=discord.Color.blue()
        )
        
        # Добавляем информацию об отправителе
        embed.add_field(name="👤 Отправитель", value=ctx.author.mention, inline=True)
        embed.add_field(name="🏰 Сервер", value=ctx.guild.name, inline=True)
        
        # Добавляем аватар сервера
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        
        embed.set_footer(text=f"ID: {ctx.guild.id} | {bot.user.name}")
        
        await member.send(embed=embed)
        
        success_embed = discord.Embed(
            title="✅ **СООБЩЕНИЕ ОТПРАВЛЕНО**",
            description=f"Сообщение успешно отправлено пользователю {member.mention}",
            color=discord.Color.green()
        )
        success_embed.add_field(name="📝 Текст", value=message[:200] + "..." if len(message) > 200 else message, inline=False)
        
        await ctx.send(embed=success_embed, delete_after=10)
        
        # Логируем отправку
        print(f"📨 Ручная отправка ЛС от {ctx.author.name} для {member.name}")
        
    except discord.Forbidden:
        error_embed = discord.Embed(
            title="❌ **ОШИБКА ОТПРАВКИ**",
            description=f"Не удалось отправить сообщение пользователю {member.mention}.\nВозможно, у него закрыты личные сообщения.",
            color=discord.Color.red()
        )
        await ctx.send(embed=error_embed)
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ **НЕИЗВЕСТНАЯ ОШИБКА**",
            description=f"Произошла ошибка: {str(e)}",
            color=discord.Color.red()
        )
        await ctx.send(embed=error_embed)

@bot.command(name='отправитьвсем')
@commands.has_permissions(administrator=True)
async def send_dm_all(ctx, *, message: str = None):
    """Отправить личное сообщение всем участникам сервера"""
    guild_id = str(ctx.guild.id)
    auto_dm_data = storage.get_guild_data(guild_id, 'auto_dm')
    
    if not message:
        # Если сообщение не указано, используем авто-ЛС шаблон
        if not auto_dm_data.get('message'):
            await ctx.send("❌ Укажите сообщение или установите авто-ЛС шаблон!")
            return
        message = auto_dm_data['message']
    
    # Подсчет участников (без ботов)
    members_to_send = [m for m in ctx.guild.members if not m.bot]
    
    if len(members_to_send) > 100:
        await ctx.send("⚠️ **ВНИМАНИЕ**: На сервере более 100 участников. Это может занять время и быть ограничено Discord API.")
    
    confirm_embed = discord.Embed(
        title="⚠️ **ПОДТВЕРЖДЕНИЕ ОТПРАВКИ**",
        description=f"Вы собираетесь отправить сообщение **всем {len(members_to_send)} участникам** сервера.",
        color=discord.Color.orange()
    )
    
    # Показываем предпросмотр
    preview = await format_dm_message(message, ctx.author, ctx.guild)
    confirm_embed.add_field(name="📝 Сообщение", value=preview[:500] + "..." if len(preview) > 500 else preview, inline=False)
    confirm_embed.add_field(name="👤 Пример для", value=ctx.author.mention, inline=True)
    confirm_embed.add_field(name="🏰 Сервер", value=ctx.guild.name, inline=True)
    confirm_embed.set_footer(text="Напишите 'подтвердить' для отправки или 'отмена' для отмены")
    
    await ctx.send(embed=confirm_embed)
    
    try:
        response = await bot.wait_for(
            'message',
            check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['подтвердить', 'отмена'],
            timeout=30.0
        )
        
        if response.content.lower() == 'отмена':
            cancel_embed = discord.Embed(
                title="❌ **ОТПРАВКА ОТМЕНЕНА**",
                color=discord.Color.red()
            )
            await ctx.send(embed=cancel_embed)
            return
        
        # Начинаем отправку
        progress_embed = discord.Embed(
            title="📤 **НАЧАЛО ОТПРАВКИ**",
            description=f"Отправка сообщения {len(members_to_send)} участникам...",
            color=discord.Color.blue()
        )
        progress_msg = await ctx.send(embed=progress_embed)
        
        sent = 0
        failed = 0
        errors = []
        
        for i, member in enumerate(members_to_send):
            try:
                # Форматируем для каждого участника отдельно
                formatted = await format_dm_message(message, member, ctx.guild)
                
                embed = discord.Embed(
                    title=f"📨 **СООБЩЕНИЕ ОТ {ctx.guild.name}**",
                    description=formatted,
                    color=discord.Color.blue()
                )
                embed.add_field(name="👤 Отправитель", value=ctx.author.mention, inline=True)
                embed.add_field(name="🏰 Сервер", value=ctx.guild.name, inline=True)
                
                if ctx.guild.icon:
                    embed.set_thumbnail(url=ctx.guild.icon.url)
                
                embed.set_footer(text=f"ID: {ctx.guild.id} | {bot.user.name}")
                
                await member.send(embed=embed)
                sent += 1
                
                # Обновляем прогресс каждые 10 отправок
                if sent % 10 == 0:
                    progress_embed.description = f"Отправлено: **{sent}**/{len(members_to_send)}\nНе удалось: **{failed}**\nПрогресс: **{(sent/len(members_to_send)*100):.1f}%**"
                    await progress_msg.edit(embed=progress_embed)
                    
                # Задержка чтобы не превысить лимиты Discord (50 сообщений в секунду)
                await asyncio.sleep(0.5)
                
            except discord.Forbidden:
                failed += 1
                errors.append(f"{member.name}: Закрытые ЛС")
            except Exception as e:
                failed += 1
                errors.append(f"{member.name}: {str(e)}")
        
        # Финальный отчет
        report_embed = discord.Embed(
            title="📊 **ОТЧЕТ ОБ ОТПРАВКЕ**",
            color=discord.Color.green() if failed == 0 else discord.Color.orange()
        )
        report_embed.add_field(name="✅ Успешно отправлено", value=f"**{sent}** участникам", inline=True)
        report_embed.add_field(name="❌ Не удалось отправить", value=f"**{failed}** участникам", inline=True)
        
        if sent > 0:
            success_rate = (sent / (sent + failed)) * 100
            report_embed.add_field(name="📈 Успешность", value=f"**{success_rate:.1f}%**", inline=True)
        
        if errors and failed < 10:  # Показываем ошибки если их немного
            error_text = "\n".join(errors[:10])
            if failed > 10:
                error_text += f"\n...и еще {failed - 10} ошибок"
            report_embed.add_field(name="📝 Ошибки", value=f"```{error_text}```", inline=False)
        
        report_embed.set_footer(text=f"Запущено: {ctx.author.name}")
        await progress_msg.edit(embed=report_embed)
        
        # Сохраняем статистику
        auto_dm_data['mass_sent'] = auto_dm_data.get('mass_sent', 0) + sent
        storage.set_guild_data(guild_id, 'auto_dm', auto_dm_data)
        
    except asyncio.TimeoutError:
        timeout_embed = discord.Embed(
            title="⏰ **ВРЕМЯ ВЫШЛО**",
            description="Операция отменена из-за неактивности.",
            color=discord.Color.red()
        )
        await ctx.send(embed=timeout_embed)

@bot.command(name='крестики')
async def tictactoe(ctx, opponent: discord.Member):
    """Крестики-нолики"""
    if opponent == ctx.author:
        await ctx.send("❌ Нельзя играть против себя!")
        return
    
    board = [['1️⃣', '2️⃣', '3️⃣'], ['4️⃣', '5️⃣', '6️⃣'], ['7️⃣', '8️⃣', '9️⃣']]
    players = {ctx.author.id: '❌', opponent.id: '⭕'}
    current = ctx.author
    
    def display():
        return '\n'.join([' | '.join(row) for row in board])
    
    embed = discord.Embed(
        title="🎮 **КРЕСТИКИ-НОЛИКИ**",
        description=f"{ctx.author.mention} (❌) vs {opponent.mention} (⭕)\n\n{display()}",
        color=discord.Color.blue()
    )
    embed.add_field(name="🎯 Ход", value=f"{current.mention} (❌)")
    msg = await ctx.send(embed=embed)
    
    for _ in range(9):
        try:
            move_msg = await bot.wait_for(
                'message',
                check=lambda m: m.author == current and m.channel == ctx.channel and m.content in ['1', '2', '3', '4', '5', '6', '7', '8', '9'],
                timeout=60.0
            )
            
            pos = int(move_msg.content) - 1
            row, col = pos // 3, pos % 3
            
            if board[row][col] in ['❌', '⭕']:
                continue
            
            board[row][col] = players[current.id]
            
            # Проверка победы
            win = False
            for i in range(3):
                if board[i][0] == board[i][1] == board[i][2] or board[0][i] == board[1][i] == board[2][i]:
                    win = True
            if board[0][0] == board[1][1] == board[2][2] or board[0][2] == board[1][1] == board[2][0]:
                win = True
            
            if win:
                reward = 150
                guild_id = str(ctx.guild.id)
                user_id = str(current.id)
                economy_data = storage.get_guild_data(guild_id, 'economy')
                economy_data[user_id] = economy_data.get(user_id, 0) + reward
                
                win_embed = discord.Embed(
                    title="🎉 **ПОБЕДА!**",
                    description=f"Победитель: {current.mention}\nНаграда: **{reward}** кредитов\n\n{display()}",
                    color=discord.Color.green()
                )
                await ctx.send(embed=win_embed)
                return
            
            # Смена игрока
            current = opponent if current == ctx.author else ctx.author
            
            embed = discord.Embed(
                title="🎮 **КРЕСТИКИ-НОЛИКИ**",
                description=f"{ctx.author.mention} (❌) vs {opponent.mention} (⭕)\n\n{display()}",
                color=discord.Color.blue()
            )
            embed.add_field(name="🎯 Ход", value=f"{current.mention} ({players[current.id]})")
            await msg.edit(embed=embed)
            
        except asyncio.TimeoutError:
            await ctx.send("⏰ Время вышло!")
            return
    
    # Ничья
    draw_embed = discord.Embed(
        title="🤝 **НИЧЬЯ!**",
        description=f"Никто не выиграл!\n\n{display()}",
        color=discord.Color.orange()
    )
    await ctx.send(embed=draw_embed)

@bot.command(name='миллионер')
@commands.cooldown(1, 300, commands.BucketType.user)
async def millionaire(ctx):
    """Кто хочет стать миллионером?"""
    questions = [
        {
            "question": "Какого цвета трава?",
            "options": ["A) Красная", "B) Синяя", "C) Зеленая", "D) Желтая"],
            "correct": "C",
            "prize": 100
        },
        {
            "question": "Сколько планет в Солнечной системе?",
            "options": ["A) 7", "B) 8", "C) 9", "D) 10"],
            "correct": "B",
            "prize": 200
        },
        {
            "question": "Столица России?",
            "options": ["A) Санкт-Петербург", "B) Москва", "C) Казань", "D) Сочи"],
            "correct": "B",
            "prize": 300
        },
        {
            "question": "Кто написал 'Войну и мир'?",
            "options": ["A) Пушкин", "B) Достоевский", "C) Толстой", "D) Гоголь"],
            "correct": "C",
            "prize": 500
        },
        {
            "question": "Сколько будет 2 + 2 * 2?",
            "options": ["A) 6", "B) 8", "C) 4", "D) 10"],
            "correct": "A",
            "prize": 1000
        }
    ]
    
    total_prize = 0
    
    for i, q in enumerate(questions, 1):
        embed = discord.Embed(
            title=f"💰 **ВОПРОС {i}**",
            description=f"На кону: **{q['prize']}** кредитов",
            color=discord.Color.gold()
        )
        embed.add_field(name="❓ Вопрос", value=q['question'], inline=False)
        embed.add_field(name="📝 Варианты", value="\n".join(q['options']), inline=False)
        await ctx.send(embed=embed)
        
        try:
            answer_msg = await bot.wait_for(
                'message',
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.content.upper() in ['A', 'B', 'C', 'D', 'ВЫХОД'],
                timeout=30.0
            )
            
            answer = answer_msg.content.upper()
            
            if answer == 'ВЫХОД':
                if i >= 4:
                    guaranteed = 300
                elif i >= 2:
                    guaranteed = 200
                else:
                    guaranteed = 0
                
                total_prize += guaranteed
                break
            
            if answer == q['correct']:
                total_prize += q['prize']
                await ctx.send(f"✅ **ПРАВИЛЬНО!** Твой выигрыш: **{total_prize}** кредитов")
                await asyncio.sleep(2)
            else:
                if i >= 4:
                    guaranteed = 300
                elif i >= 2:
                    guaranteed = 200
                else:
                    guaranteed = 0
                
                total_prize = guaranteed
                await ctx.send(f"❌ **НЕПРАВИЛЬНО!** Правильный ответ: **{q['correct']}**\nТы забираешь **{guaranteed}** кредитов")
                break
                
        except asyncio.TimeoutError:
            if i >= 4:
                guaranteed = 300
            elif i >= 2:
                guaranteed = 200
            else:
                guaranteed = 0
            
            total_prize = guaranteed
            await ctx.send(f"⏰ **ВРЕМЯ ВЫШЛО!** Ты забираешь **{guaranteed}** кредитов")
            break
    
    # Выдача награды
    if total_prize > 0:
        guild_id = str(ctx.guild.id)
        user_id = str(ctx.author.id)
        economy_data = storage.get_guild_data(guild_id, 'economy')
        economy_data[user_id] = economy_data.get(user_id, 0) + total_prize
        storage.set_guild_data(guild_id, 'economy', economy_data)
        
        final_embed = discord.Embed(
            title="🎉 **ИГРА ОКОНЧЕНА**",
            description=f"Поздравляем, {ctx.author.mention}!",
            color=discord.Color.gold()
        )
        final_embed.add_field(name="💰 Итоговый выигрыш", value=f"**{total_prize}** кредитов", inline=False)
        await ctx.send(embed=final_embed)

# ==================== RPG ====================
@bot.command(name='rpg')
async def rpg(ctx, action: str = None):
    """Текстовая RPG игра"""
    guild_id = str(ctx.guild.id)
    user_id = str(ctx.author.id)
    
    rpg_data = storage.get_guild_data(guild_id, 'rpg_saves')
    
    if not action:
        embed = discord.Embed(
            title="⚔️ **RPG ИГРА**",
            description="Приключенческая текстовая RPG",
            color=discord.Color.dark_purple()
        )
        
        if user_id in rpg_data and rpg_data[user_id].get('active'):
            save = rpg_data[user_id]
            embed.add_field(name="🎮 Продолжить игру", value=f"`!rpg играть`\nЛокация: {save.get('location', 'Начало')}", inline=False)
        else:
            embed.add_field(name="🆕 Новая игра", value="`!rpg начать`", inline=False)
        
        await ctx.send(embed=embed)
        return
    
    action = action.lower()
    
    if action == 'начать':
        rpg_data[user_id] = {
            'active': True,
            'location': 'Начальная деревня',
            'health': 100,
            'max_health': 100,
            'level': 1,
            'gold': 50,
            'inventory': ['Меч', 'Зелье здоровья'],
            'quests': ['Найти сокровище']
        }
        storage.set_guild_data(guild_id, 'rpg_saves', rpg_data)
        
        embed = discord.Embed(
            title="🎮 **НОВАЯ ИГРА НАЧАТА**",
            description="Ты в Начальной деревне. Куда пойдешь?",
            color=discord.Color.green()
        )
        embed.add_field(name="📍 Локация", value="Начальная деревня", inline=True)
        embed.add_field(name="❤️ Здоровье", value="100/100", inline=True)
        embed.add_field(name="💰 Золото", value="50", inline=True)
        await ctx.send(embed=embed)
    
    elif action == 'играть':
        if user_id not in rpg_data or not rpg_data[user_id].get('active'):
            await ctx.send("❌ Сначала начни игру: `!rpg начать`")
            return
        
        save = rpg_data[user_id]
        events = [
            "Ты встретил торговца.",
            "На тебя напали бандиты!",
            "Ты нашел сундук с сокровищами.",
            "Ты заблудился в лесу.",
            "Ты нашел древний артефакт."
        ]
        
        event = random.choice(events)
        embed = discord.Embed(
            title=f"📍 **{save['location']}**",
            description=event,
            color=discord.Color.dark_green()
        )
        embed.add_field(name="❤️ Здоровье", value=f"{save['health']}/{save['max_health']}", inline=True)
        embed.add_field(name="⭐ Уровень", value=save['level'], inline=True)
        embed.add_field(name="💰 Золото", value=save['gold'], inline=True)
        
        await ctx.send(embed=embed)

@bot.command(name='добавить')
async def invite(ctx):
    """Получить ссылку для добавления бота"""
    embed = discord.Embed(
        title="➕ **ДОБАВИТЬ БОТА**",
        description=f"[Нажми здесь](https://discord.com/oauth2/authorize?client_id={bot.user.id}&scope=bot&permissions=8) чтобы добавить бота на свой сервер!",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

# ==================== ХЕЛП ====================
@bot.command(name='хелп')
async def help_command(ctx):
    embed = discord.Embed(
        title="📚 **GALAXYLITE V1.0 PRO - ПОМОЩЬ**",
        description="Все доступные команды бота:",
        color=discord.Color.blue()
    )
    
    # О боте
    embed.add_field(
        name="👑 **О БОТЕ**",
        value="`!создатель` - Информация о создателе бота",
        inline=False
    )
        
    # Свадьба
    embed.add_field(
        name="💍 **СВАДЕБНЫЕ КОМАНДЫ**",
        value=(
            "`!предложить @игрок` - Предложить брак (100 кредитов)\n"
            "`!принять` - Принять предложение\n"
            "`!отказать` - Отказать от предложения\n"
            "`!брак [@игрок]` - Информация о браке\n"
            "`!развод` - Подать на развод\n"
            "`!подарок @игрок сумма` - Подарить кредиты супругу\n"
            "`!купитьвместе товар` - Купить что-то из общего бюджета"
        ),
        inline=False
    )
    
    # Игры
    embed.add_field(
        name="🎮 **ИГРЫ И РАЗВЛЕЧЕНИЯ**",
        value=(
            "`!рандом` - случайное число\n"
            "`!монетка` - подбросить монетку\n"
            "`!шар` - Магический шар предсказаний\n"
            "`!угадай` - Угадай число (6 попыток)\n"
            "`!slots [ставка]` - Игровой автомат\n"
            "`!rpg` - Текстовая RPG игра\n"
            "`!виселица` - Игра в виселицу\n"
            "`!крестики @игрок` - Крестики-нолики\n"
            "`!миллионер` - Кто хочет стать миллионером?"
        ),
        inline=False
    )
    
    # Экономика
    embed.add_field(
        name="💰 **ЭКОНОМИКА**",
        value=(
            "`!баланс [@пользователь]` - Проверить баланс\n"
            "`!ежедневно` - Получить ежедневную награду"
        ),
        inline=False
    )
    
    # Панель управления
    embed.add_field(
        name="🎨 **ПАНЕЛЬ УПРАВЛЕНИЯ**",
        value=(
            "`!панель создать [тип]` - Создать панель\n"
            "`!панель удалить` - Удалить панель\n"
            "`!панель скорость X` - Изменить скорость (0.5-5)\n"
            "`!панель тип набор` - Сменить градиент\n"
            "`!панель список` - Доступные градиенты"
        ),
        inline=False
    )
            
    # Утилиты
    embed.add_field(
        name="ℹ️ **УТИЛИТЫ**",
        value=(
            "`!юзер @пользователь` - Информация о пользователе\n"
            "`!сервер` - Информация о сервере\n"
            "`!пинг` - Проверить задержку бота\n"
            "`!хелп` - Показать это меню"
        ),
        inline=False
    )
    
    embed.set_footer(text="GalaxyLite V1.0 Pro | Создатель: retre_helis | Префикс: ! | Всего команд: 45+")
    await ctx.send(embed=embed)

@bot.command(name='админхелп', hidden=True)
@commands.has_permissions(administrator=True)
async def admin_help(ctx):
    """Помощь для администраторов (скрытая команда)"""
    embed = discord.Embed(
        title="🔧 **АДМИН КОМАНДЫ GALAXYLITE**",
        description="Только для администраторов сервера",
        color=discord.Color.red()
    )
    
    embed.add_field(
        name="📨 **АВТОМАТИЧЕСКИЕ ЛИЧНЫЕ СООБЩЕНИЯ**",
        value=(
            "`!автолс` - Настройки авто-ЛС\n"
            "`!автолс вкл/выкл` - Включить/выключить\n"
            "`!автолс сообщение текст` - Установить шаблон\n"
            "`!автолс тест` - Отправить тест себе\n"
            "`!автолс статистика` - Статистика отправок\n"
            "`!автолс сброс` - Сбросить настройки\n\n"
            "**Доступные переменные:**\n"
            "`{user}` - Имя пользователя\n"
            "`{user_mention}` - Упоминание\n"
            "`{server_name}` - Название сервера\n"
            "`{member_count}` - Количество участников\n"
            "`{join_date}` - Дата присоединения\n"
            "`{timestamp}` - Текущее время"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📨 **РУЧНАЯ ОТПРАВКА ЛС**",
        value=(
            "`!отправить @пользователь [сообщение]` - Отправить ЛС\n"
            "`!отправитьвсем [сообщение]` - Отправить всем участникам\n"
            "*Если сообщение не указано, используется авто-ЛС шаблон*"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🛡️ **МОДЕРАЦИЯ**",
        value=(
            "`!варн @участник [причина]` - Выдать предупреждение\n"
            "`!варны [@участник]` - Посмотреть предупреждения\n"
            "`!анварн @участник` - Снять предупреждение\n"
            "`!снятьварн @участник ID` - Снять конкретное предупреждение\n"
            "`!кик @участник [причина]` - Кикнуть участника\n"
            "`!бан @участник [причина]` - Забанить участника\n"
            "`!разбан ID` - Разбанить по ID\n"
            "`!мут @участник время [причина]` - Выдать мут\n"
            "`!размут @участник` - Снять мут\n"
            "`!очистить [кол-во]` - Удалить сообщения"
        ),  # <--- ЗАКРЫВАЮЩАЯ СКОБКА ЗДЕСЬ
        inline=False  # <--- ПАРАМЕТР ЗДЕСЬ
    )  # <--- ЗАКРЫВАЮЩАЯ СКОБКА ДЛЯ ВСЕГО add_field
    
    embed.add_field(
        name="🚫 **АВТОМОДЕРАЦИЯ**",
        value=(
            "`!автомод` - Показать настройки\n"
            "`!автомод вкл/выкл` - Включить/выключить\n"
            "`!автомод настройки` - Детальные настройки\n"
            "`!автомод установить параметр значение` - Изменить параметр\n"
            "`!автомод логи` - Показать логи нарушений\n"
            "`!автомод сброс @пользователь` - Сбросить предупреждения\n"
            "`!автомод модуль название вкл/выкл` - Управление модулями\n"
            "`!добавитьслово слово` - Добавить запрещенное слово\n"
            "`!удалитьслово слово` - Удалить запрещенное слово\n"
            "`!списокслов` - Показать запрещенные слова"
        ),
        inline=False
    )
    
    embed.add_field(
        name="👋 **ПРИВЕТСТВИЯ В КАНАЛЕ**",
        value=(
            "`!приветствие` - Настройка приветствий\n"
            "`!приветствие вкл/выкл` - Включить/выключить\n"
            "`!приветствие канал #канал` - Установить канал\n"
            "`!приветствие сообщение текст` - Изменить текст\n"
            "`!приветствие баннер [ссылка]` - Установить баннер\n"
            "`!приветствие правило` - Управление правилами\n"
            "`!приветствие сброс` - Сбросить настройки"
        ),
        inline=False
    )
    
    await ctx.send(embed=embed)

# ==================== ЗАПУСК БОТА ====================
@bot.event
async def on_ready():
    print(f"✅ GalaxyLite V1.0 Pro запущен!")
    print(f"✅ Подключен к {len(bot.guilds)} серверам")
    print(f"✅ Готов к работе!")
    print(f"✅ Система градиентной панели активирована!")
    
    # Запускаем восстановление активных панелей
    for guild in bot.guilds:
        guild_id = str(guild.id)
        gradient_settings = storage.get_guild_data(guild_id, 'gradient_settings')
        if gradient_settings.get('active', False):
            print(f"🔄 Восстановление панели для сервера {guild.name}")
    
    await bot.change_presence(
        activity=discord.Game(name="GalaxyLite V1.0 Pro | !хелп"),
        status=discord.Status.online
    )

# Запускаем бота
if __name__ == "__main__":
    print("🚀 Запуск GalaxyLite V1.0 Pro...")
    print("👑 создатель retre_helis 👑")
    bot.run(TOKEN)
