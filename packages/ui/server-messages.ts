// Translate API diagnostics at the client boundary; the server protocol stays unchanged.
export const serverMessages: Record<string, string> = {
  "Ожидается JSON-объект": "Expected a JSON object",
  "Ошибка сервера; подробности в журнале":
    "Server error; see the log for details",
  "{0}: ожидается конечное число": "{0}: expected a finite number",
  "{0}: диапазон {1}…{2}": "{0}: range {1}…{2}",
  "ID: 1–80 букв, цифр, _, ., : или -":
    "ID: 1–80 letters, digits, _, ., : or -",
  "Текст: не более {0} символов": "Text: at most {0} characters",
  "Нейрон должен быть объектом": "A neuron must be an object",
  "{0}: неизвестный режим": "{0}: unknown mode",
  "Ожидается объект сети": "Expected a network object",
  "Поддерживается только среда BUG": "Only the BUG environment is supported",
  "Неизвестная версия сети": "Unknown network version",
  "Лимит: 1 000 000 нейронов": "Limit: 1,000,000 neurons",
  "Лимит: 500 000 связей": "Limit: 500,000 connections",
  "Повторяющиеся ID нейронов": "Duplicate neuron IDs",
  "Некорректный список ганглиев": "Invalid ganglion list",
  "Некорректный список рамок": "Invalid frame list",
  "Ганглий должен быть объектом": "A ganglion must be an object",
  "Повторяющийся ID ганглия": "Duplicate ganglion ID",
  "Участники ганглия должны быть списком ID":
    "Ganglion members must be a list of IDs",
  "Некорректные участники ганглия": "Invalid ganglion members",
  "Нейрон может входить только в один ганглий":
    "A neuron can belong to only one ganglion",
  "Синапс должен быть объектом": "A synapse must be an object",
  "Связь {0}: неизвестный ID": "Connection {0}: unknown ID",
  "Неизвестный тип синапса": "Unknown synapse type",
  "{0}: знак связи противоречит полярности нейрона":
    "{0}: connection sign conflicts with neuron polarity",
  "Повторяющийся ID синапса": "Duplicate synapse ID",
  "С учётом коннекторов превышен лимит 500 000 связей":
    "Connector expansion exceeds the limit of 500,000 connections",
  "Рамка должна быть объектом": "A frame must be an object",
  "Настройки мира должны быть объектом": "World settings must be an object",
  "Неизвестный режим угрозы": "Unknown threat mode",
  "Назначения должны быть объектом": "Bindings must be an object",
  "{0}: нейрон {1} не существует": "{0}: neuron {1} does not exist",
  "Неизвестная версия эксперимента": "Unknown experiment version",
  "Мир должен быть объектом": "The world must be an object",
  "Объекты и зоны должны быть списками объектов":
    "Objects and zones must be lists of objects",
  "Точка старта должна быть объектом": "The starting point must be an object",
  "Неизвестный режим полярности": "Unknown polarity mode",
  "Слишком много связей; уменьшите плотность":
    "Too many connections; reduce density",
  "Коридоры должны быть шире 50 единиц":
    "Corridors must be wider than 50 units",
  "Выберите два разных существующих ганглия":
    "Select two different existing ganglia",
  "Неизвестный тип связи": "Unknown connection type",
  "Неизвестный тип нейронов-источников": "Unknown source neuron type",
  "Неизвестный тип целевых нейронов": "Unknown target neuron type",
  "Лимит: 100 зон пищи": "Limit: 100 food zones",
  "Зона вне арены": "Zone outside the arena",
  "Лимит: 2500 объектов": "Limit: 2,500 objects",
  "Неизвестный объект": "Unknown object",
  "Препятствие вне арены": "Obstacle outside the arena",
  "Препятствие пересекает жука": "Obstacle overlaps the bug",
  "Объект пересекает стену": "Object overlaps a wall",
  "Нет свободного места для жука": "No free space for the bug",
  "Устройство {0} недоступно; выбран CPU. {1}":
    "Device {0} is unavailable; using CPU. {1}",
  "Ожидается JSON-объект команды": "Expected a JSON command object",
  "Сначала поставьте симуляцию на паузу": "Pause the simulation first",
  "Неизвестная команда": "Unknown command",
  "Нейрон не найден": "Neuron not found",
  "Проект изменён в другом окне. Данные обновлены; повторите действие.":
    "The project changed in another window. Data refreshed; try again.",
  "Укажите вычислительное устройство": "Specify a compute device",
  "Ганглий не найден": "Ganglion not found",
  "Жук окажется вне новой арены": "The bug would be outside the new arena",
  "Объекты окажутся вне новой арены": "Objects would be outside the new arena",
  "Зоны окажутся вне новой арены": "Zones would be outside the new arena",
  "Неизвестный вид объектов": "Unknown object kind",
  "Здесь недостаточно места для жука": "Not enough space for the bug here",
  "Неизвестное действие": "Unknown action",
  "Установите requirements-gpu.txt и перезапустите сервер":
    "Install requirements-gpu.txt and restart the server",
  "Отключите PYTORCH_ENABLE_MPS_FALLBACK и перезапустите сервер":
    "Disable PYTORCH_ENABLE_MPS_FALLBACK and restart the server",
  "Metal/MPS недоступен на этом сервере":
    "Metal/MPS is unavailable on this server",
  "Нет доступного CUDA GPU или установлена сборка PyTorch без CUDA":
    "No CUDA GPU is available, or PyTorch was built without CUDA",
  "Неизвестное вычислительное устройство": "Unknown compute device",
  "Не удалось запустить {0}: {1}": "Could not start {0}: {1}",
};
