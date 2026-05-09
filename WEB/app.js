import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  CSS2DRenderer,
  CSS2DObject,
} from "three/addons/renderers/CSS2DRenderer.js";

// ========== Система логирования (без зависимостей от DOM) ==========
const Logger = {
  logElement: null,

  init() {
    // Ждем появления элемента
    this.logElement = document.getElementById("log-content");
    if (!this.logElement) {
      console.log("Ожидание создания log-content...");
      return false;
    }
    return true;
  },

  add(message, type = "info") {
    // Если лог еще не инициализирован, просто выводим в консоль
    if (!this.logElement) {
      console.log(`[${type}] ${message}`);
      return;
    }

    const entry = document.createElement("div");
    entry.className = `log-entry log-${type}`;
    const time = new Date().toLocaleTimeString();
    entry.innerHTML = `<span style="color:#888">[${time}]</span> ${message}`;
    this.logElement.appendChild(entry);
    entry.scrollIntoView({ behavior: "smooth", block: "nearest" });

    const consoleMethod =
      type === "error" ? "error" : type === "warning" ? "warn" : "log";
    console[consoleMethod](message);
  },

  clear() {
    if (this.logElement) {
      this.logElement.innerHTML = "";
      this.add("Лог очищен", "info");
    }
  },

  info(message) {
    this.add(message, "info");
  },
  success(message) {
    this.add(message, "success");
  },
  error(message) {
    this.add(message, "error");
  },
  warning(message) {
    this.add(message, "warning");
  },
};

// ========== Основные переменные ==========
let scene, camera, renderer, labelRenderer, controls;
let mainGroup;
let currentModel = null;
let pointsCount = 0;
let segmentsCount = 0;

// Состояние измерения
let measuringMode = false;
let measurePoints = [];
let measureObjects = [];

// Состояние сечения
let sectionPlane = null;
let sectionPlaneVisible = false;
let isClipped = false;

// UI элементы
let statsElement, coordsElement;
let lastTime = performance.now();
let frameCount = 0;

// Настройки линий
let lineWidth = 3;

// ========== Инициализация ==========
async function init() {
  try {
    console.log("Начало инициализации...");

    // Ждем небольшой паузы для загрузки DOM
    await new Promise((resolve) => setTimeout(resolve, 100));

    // Инициализируем логгер
    Logger.init();
    Logger.info("Инициализация 3D сцены...");

    // Проверяем наличие всех элементов
    statsElement = document.getElementById("stats");
    coordsElement = document.getElementById("coords");

    if (!statsElement) console.warn("stats element not found");
    if (!coordsElement) console.warn("coords element not found");

    // Сцена
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x30303a);

    // Камера
    camera = new THREE.PerspectiveCamera(
      45,
      window.innerWidth / window.innerHeight,
      0.1,
      10000,
    );
    camera.position.set(500, 400, 600);
    camera.lookAt(0, 0, 0);

    // Рендерер
    renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    document.body.appendChild(renderer.domElement);

    // CSS2 рендерер для текста
    labelRenderer = new CSS2DRenderer();
    labelRenderer.setSize(window.innerWidth, window.innerHeight);
    labelRenderer.domElement.style.position = "absolute";
    labelRenderer.domElement.style.top = "0px";
    labelRenderer.domElement.style.left = "0px";
    labelRenderer.domElement.style.pointerEvents = "none";
    document.body.appendChild(labelRenderer.domElement);

    // Управление
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.rotateSpeed = 1.5;
    controls.zoomSpeed = 1.2;
    controls.panSpeed = 0.8;

    // Группа для модели
    mainGroup = new THREE.Group();
    scene.add(mainGroup);

    // Вспомогательные элементы
    addLighting();
    addGridHelper();
    addAxesHelper();

    // Запуск анимации
    animate();

    // Настройка UI после загрузки
    setupUI();

    // Обработка resize
    window.addEventListener("resize", onWindowResize);

    // Настройка измерения точек
    setupMeasurementClick();

    Logger.success("Приложение успешно инициализировано");

    // Обновляем статус
    if (statsElement) {
      statsElement.innerHTML = "⚡ Готов к работе | Ожидание файла";
    }
  } catch (err) {
    console.error("Ошибка инициализации:", err);
    Logger.error(`Ошибка инициализации: ${err.message}`);
  }
}

// ========== Освещение ==========
// ========== Освещение с настраиваемой позицией ==========
function addLighting() {
  // 1. Ambient свет (базовая освещенность)
  const ambientLight = new THREE.AmbientLight(0x666666, 0.6);
  scene.add(ambientLight);

  // 2. Основной свет - сверху на высоте 4000
  const topLight = new THREE.DirectionalLight(0xffffff, 0.8);
  topLight.position.set(0, 4000, 100); // X:100, Y:4000 (высота), Z:0
  topLight.castShadow = false;
  scene.add(topLight);

  // 3. Боковой свет - сбоку на 1000 мм (например, справа и спереди)
  const sideLight = new THREE.DirectionalLight(0xffaa88, 0.5);
  sideLight.position.set(1000, 1500, 1000); // X:1000 (справа), Y:1500, Z:1000 (спереди)
  sideLight.castShadow = false;
  scene.add(sideLight);

  // Опционально: второй боковой свет слева для равномерности
  const leftLight = new THREE.DirectionalLight(0x88aaff, 0.3);
  leftLight.position.set(-1000, 1500, -500); // X:-1000 (слева), Y:500, Z:500
  leftLight.castShadow = false;
  scene.add(leftLight);

  // Визуализация позиции источников света (для отладки, можно удалить)
  if (true) {
    // Установите false чтобы скрыть маркеры
    const sphereGeo = new THREE.SphereGeometry(20, 8, 8);

    const topMarker = new THREE.Mesh(
      sphereGeo,
      new THREE.MeshStandardMaterial({ color: 0xffff00, emissive: 0x442200 }),
    );
    topMarker.position.set(0, 4000, 100);
    scene.add(topMarker);

    const sideMarker = new THREE.Mesh(
      sphereGeo,
      new THREE.MeshStandardMaterial({ color: 0xffaa66, emissive: 0x442200 }),
    );
    sideMarker.position.set(1000, 500, 1000);
    scene.add(sideMarker);

    const leftMarker = new THREE.Mesh(
      sphereGeo,
      new THREE.MeshStandardMaterial({ color: 0x66aaff, emissive: 0x002244 }),
    );
    leftMarker.position.set(-1000, 1500, -500);
    scene.add(leftMarker);

    // Добавляем линии от источника света до центра сцены
    const center = new THREE.Vector3(0, 0, 0);

    const lineMat = new THREE.LineBasicMaterial({ color: 0xffaa66 });

    const topLineGeo = new THREE.BufferGeometry().setFromPoints([
      topMarker.position,
      center,
    ]);
    const topLine = new THREE.Line(topLineGeo, lineMat);
    scene.add(topLine);

    const sideLineGeo = new THREE.BufferGeometry().setFromPoints([
      sideMarker.position,
      center,
    ]);
    const sideLine = new THREE.Line(sideLineGeo, lineMat);
    scene.add(sideLine);

    const leftLineGeo = new THREE.BufferGeometry().setFromPoints([
      leftMarker.position,
      center,
    ]);
    const leftLine = new THREE.Line(leftLineGeo, lineMat);
    scene.add(leftLine);
  }
}

// ========== Вспомогательные элементы ==========
function addGridHelper() {
  const gridHelper = new THREE.GridHelper(2000, 20, 0x888888, 0x444444);
  gridHelper.position.y = -0.1;
  gridHelper.material.transparent = true;
  gridHelper.material.opacity = 0.4;
  scene.add(gridHelper);
}

function addAxesHelper() {
  const axesHelper = new THREE.AxesHelper(500);
  axesHelper.material.transparent = true;
  axesHelper.material.opacity = 0.3;
  scene.add(axesHelper);

  const makeAxisLabel = (text, color, position) => {
    const div = document.createElement("div");
    div.textContent = text;
    div.style.color = color;
    div.style.fontSize = "16px";
    div.style.fontWeight = "bold";
    div.style.textShadow = "1px 1px 0px black";
    const label = new CSS2DObject(div);
    label.position.copy(position);
    scene.add(label);
  };

  makeAxisLabel("Y", "#ff4444", new THREE.Vector3(600, 0, 0));
  makeAxisLabel("Z", "#44ff44", new THREE.Vector3(0, 3100, 0));
  makeAxisLabel("X", "#4444ff", new THREE.Vector3(0, 0, 30));
}

// ========== Создание толстой линии с помощью TubeGeometry ==========
function createThickLine(points, color, radius) {
  if (points.length < 2) return null;

  try {
    // Создаем кривую из точек
    const curve = new THREE.CatmullRomCurve3(points);

    // Минимальное количество сегментов для производительности
    const tubularSegments = Math.max(20, Math.floor(points.length * 1.2));
    const radialSegments = 8; // 6-гранник для скорости

    const geometry = new THREE.TubeGeometry(
      curve,
      tubularSegments,
      radius,
      radialSegments,
      false,
    );

    //const material = new THREE.MeshStandardMaterial({
    //  color: color,
    //  roughness: 0.5,
    //  metalness: 0.3,
    //});

    // Самый матовый вариант - MeshStandardMaterial с параметрами:
    // const material = new THREE.MeshStandardMaterial({
    //   color: color,
    //   roughness: 1.0, // Максимальная шероховатость
    //   metalness: 0.0, // Ноль металличности
    //   emissive: 0x000000,
    //   emissiveIntensity: 0,
    //   flatShading: true,
    //   side: THREE.DoubleSide,
    // });

    const material = new THREE.MeshLambertMaterial({
      color: color,
      flatShading: true,
    });

    //const material = new THREE.MeshPhongMaterial({
    //  color: color,
    //  shininess: 10, // Низкий блеск (0-100, чем меньше, тем матовее)
    //  specular: 0x111111, // Темный цвет бликов
    //  flatShading: true,
    //});

    const tube = new THREE.Mesh(geometry, material);
    tube.castShadow = false;
    tube.receiveShadow = false;

    return tube;
  } catch (err) {
    console.warn("Ошибка создания трубки:", err);
    return null;
  }
}

// ========== Создание модели из сегментов ==========
function createModelFromSegments(segments, color, radius) {
  const group = new THREE.Group();
  let tubeCount = 0;

  for (const segment of segments) {
    if (segment.length < 2) continue;

    // Конвертируем точки в Vector3 (меняем Y и Z для удобства)
    const points = segment.map((p) => new THREE.Vector3(p.x, p.z, p.y));

    // Для длинных сегментов разбиваем на части
    const maxPointsPerTube = 1000;

    if (points.length <= maxPointsPerTube) {
      const tube = createThickLine(points, color, radius);
      if (tube) {
        group.add(tube);
        tubeCount++;
      }
    } else {
      // Разбиваем на части
      for (let i = 0; i < points.length - 1; i += maxPointsPerTube - 1) {
        const chunk = points.slice(
          i,
          Math.min(i + maxPointsPerTube, points.length),
        );
        if (chunk.length >= 2) {
          const tube = createThickLine(chunk, color, radius);
          if (tube) {
            group.add(tube);
            tubeCount++;
          }
        }
      }
    }
  }

  Logger.info(`Создано трубок: ${tubeCount}`);
  return group;
}

// ========== Парсинг G-code ==========
class GCodeParser {
  constructor() {
    this.points = [];
    this.segments = [];
  }

  parse(content) {
    this.points = [];
    this.segments = [];

    const lines = content.split("\n");
    let currentPos = { x: 0, y: 0, z: 0 };
    let currentPath = [{ ...currentPos }];

    for (const line of lines) {
      if (
        !line.trim() ||
        line.startsWith(";") ||
        line.startsWith("(") ||
        line.startsWith("%")
      ) {
        continue;
      }

      const parts = line.trim().split(/\s+/);
      let isG1 = false;
      let newPos = { ...currentPos };
      let hasMove = false;

      for (const part of parts) {
        if (part === "G1" || part === "G01") {
          isG1 = true;
        } else if (part.startsWith("X")) {
          newPos.x = parseFloat(part.substring(1));
          hasMove = true;
        } else if (part.startsWith("Y")) {
          newPos.y = parseFloat(part.substring(1));
          hasMove = true;
        } else if (part.startsWith("Z")) {
          newPos.z = parseFloat(part.substring(1));
          hasMove = true;
        }
      }

      if (isG1 && hasMove) {
        currentPath.push(newPos);
        currentPos = newPos;
      } else if (hasMove) {
        if (currentPath.length > 1) {
          this.segments.push([...currentPath]);
        }
        currentPath = [{ ...newPos }];
        currentPos = newPos;
      }
    }

    if (currentPath.length > 1) {
      this.segments.push([...currentPath]);
    }

    for (const seg of this.segments) {
      for (const pt of seg) {
        this.points.push(pt);
      }
    }

    Logger.info(
      `Парсинг завершен. Сегментов: ${this.segments.length}, точек: ${this.points.length}`,
    );
    return this.segments.length > 0;
  }

  getBounds() {
    if (this.points.length === 0)
      return { min: { x: 0, y: 0, z: 0 }, max: { x: 100, y: 100, z: 100 } };

    let minX = Infinity,
      minY = Infinity,
      minZ = Infinity;
    let maxX = -Infinity,
      maxY = -Infinity,
      maxZ = -Infinity;

    for (const pt of this.points) {
      minX = Math.min(minX, pt.x);
      minY = Math.min(minY, pt.y);
      maxX = Math.max(maxX, pt.x);
      maxY = Math.max(maxY, pt.y);
      minZ = Math.min(minZ, pt.z);
      maxZ = Math.max(maxZ, pt.z);
    }

    return {
      min: { x: minX, y: minY, z: minZ },
      max: { x: maxX, y: maxY, z: maxZ },
    };
  }
}

// ========== Загрузка файла ==========
async function loadGCode(file) {
  const statusDiv = document.getElementById("file-status");
  const progressBar = document.getElementById("progress-bar");
  const progressFill = document.getElementById("progress-fill");

  if (!statusDiv) return;

  statusDiv.innerHTML = "⏳ Загрузка файла...";
  statusDiv.style.color = "#ff9800";
  if (progressBar) progressBar.style.display = "block";
  if (progressFill) progressFill.style.width = "30%";

  Logger.info(`Загрузка: ${file.name} (${(file.size / 1024).toFixed(2)} KB)`);

  try {
    const content = await file.text();
    if (progressFill) progressFill.style.width = "60%";

    const parser = new GCodeParser();
    statusDiv.innerHTML = "⏳ Парсинг G-code...";

    if (parser.parse(content)) {
      if (progressFill) progressFill.style.width = "80%";

      const bounds = parser.getBounds();
      const segments = parser.segments;

      // Центрирование модели
      const centerX = (bounds.min.x + bounds.max.x) / 2;
      //const centerZ = (bounds.min.z + bounds.max.z) / 2;
      const centerY = (bounds.min.y + bounds.max.y) / 2;

      for (const seg of segments) {
        for (const pt of seg) {
          pt.x -= centerX;
          pt.y -= centerY;
          //pt.z -= centerZ;
        }
      }

      if (currentModel) {
        mainGroup.remove(currentModel);
      }

      const color = document.getElementById("color-picker")?.value || "#f4a460";
      const radius =
        parseFloat(document.getElementById("thickness-slider")?.value || "5") *
        0.5;

      statusDiv.innerHTML = "⏳ Создание 3D модели...";
      Logger.info(`Создание модели (диаметр: ${radius.toFixed(2)})...`);

      currentModel = createModelFromSegments(segments, color, radius);
      currentModel.userData = {
        bounds: bounds,
        segments: segments,
        radius: radius, // Сохраняем текущий радиус
      };

      mainGroup.add(currentModel);
      pointsCount = parser.points.length;
      segmentsCount = segments.length;

      if (progressFill) progressFill.style.width = "100%";
      statusDiv.innerHTML = `✅ Загружено: ${pointsCount.toLocaleString()} точек, ${segmentsCount} сегментов`;
      statusDiv.style.color = "#4caf50";

      Logger.success(
        `Модель создана! Точек: ${pointsCount}, объектов: ${currentModel.children.length}`,
      );

      // Настройка камеры
      const maxDim = Math.max(
        bounds.max.x - bounds.min.x,
        bounds.max.y - bounds.min.y,
        bounds.max.z - bounds.min.z,
      );
      const distance = maxDim * 1.5;
      camera.position.set(distance * 0.8, distance * 0.6, distance);
      controls.target.set(0, 0, 0);
      controls.update();
    } else {
      statusDiv.innerHTML = "❌ Ошибка: Не удалось распарсить G-code";
      Logger.error("Ошибка парсинга G-code");
    }

    setTimeout(() => {
      if (progressBar) progressBar.style.display = "none";
      if (progressFill) progressFill.style.width = "0%";
    }, 1000);
  } catch (err) {
    statusDiv.innerHTML = `❌ Ошибка: ${err.message}`;
    Logger.error(`Ошибка: ${err.message}`);
    if (progressBar) progressBar.style.display = "none";
  }
}

// ========== Обновление внешнего вида ==========
function updateModelAppearance() {
  if (!currentModel) return;

  const color = document.getElementById("color-picker")?.value || "#f4a460";
  const newRadius =
    parseFloat(document.getElementById("thickness-slider")?.value || "6") * 0.5;
  const opacity =
    parseInt(document.getElementById("opacity-slider")?.value || "100") / 100;

  // Получаем текущий радиус
  const currentRadius = currentModel.userData?.radius || newRadius;

  // Проверяем, изменился ли радиус
  if (Math.abs(currentRadius - newRadius) > 0.001) {
    // Радиус изменился - пересоздаем модель
    Logger.info(
      `Изменение диаметра: ${currentRadius.toFixed(1)} → ${newRadius.toFixed(1)}`,
    );
    regenerateModel(newRadius, color, opacity);
  } else {
    // Только меняем цвет и прозрачность
    currentModel.children.forEach((child) => {
      if (child.isMesh) {
        child.material.color.set(color);
        child.material.opacity = opacity;
        child.material.transparent = opacity < 1;
      }
    });
  }
}

// ========== Пересоздание модели с новым радиусом ==========
function regenerateModel(radius, color, opacity) {
  if (
    !currentModel ||
    !currentModel.userData ||
    !currentModel.userData.segments
  ) {
    Logger.warning("Нет данных для пересоздания модели");
    return;
  }

  const segments = currentModel.userData.segments;

  // Показываем индикатор загрузки
  const statusDiv = document.getElementById("file-status");
  const originalText = statusDiv?.innerHTML;
  if (statusDiv) {
    statusDiv.innerHTML = "⏳ Обновление толщины линий...";
    statusDiv.style.color = "#ff9800";
  }

  // Используем setTimeout чтобы не блокировать UI
  setTimeout(() => {
    try {
      // Создаем новую модель
      const newModel = createModelFromSegments(segments, color, radius);
      newModel.userData = {
        ...currentModel.userData,
        radius: radius,
      };

      // Применяем прозрачность
      newModel.children.forEach((child) => {
        if (child.isMesh) {
          child.material.opacity = opacity;
          child.material.transparent = opacity < 1;
        }
      });

      // Заменяем модель
      mainGroup.remove(currentModel);
      currentModel = newModel;
      mainGroup.add(currentModel);

      // Если было активное сечение, применяем его заново
      if (isClipped && sectionPlane) {
        applyClipping("right");
      }

      Logger.success(`Модель обновлена: диаметр ${radius.toFixed(1)}`);

      if (statusDiv) {
        statusDiv.innerHTML = originalText || "Готово";
        statusDiv.style.color = "#4caf50";
        setTimeout(() => {
          if (statusDiv.innerHTML === "Готово") {
            statusDiv.innerHTML = `✅ Загружено: ${pointsCount.toLocaleString()} точек, ${segmentsCount} сегментов`;
          }
        }, 1000);
      }
    } catch (err) {
      Logger.error(`Ошибка обновления модели: ${err.message}`);
      if (statusDiv) {
        statusDiv.innerHTML = originalText || "Готово";
      }
    }
  }, 10);
}

// ========== Настройка UI ==========
function setupUI() {
  // Файл
  const fileInput = document.getElementById("file-input");
  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      if (e.target.files.length > 0) {
        loadGCode(e.target.files[0]);
      }
    });
  }

  // Ползунки
  const thicknessSlider = document.getElementById("thickness-slider");
  if (thicknessSlider) {
    thicknessSlider.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      const display = document.getElementById("thickness-value");
      if (display) display.textContent = val.toFixed(1);
      updateModelAppearance(); // Эта функция теперь будет пересоздавать модель при изменении радиуса
    });
  }

  const colorPicker = document.getElementById("color-picker");
  if (colorPicker) {
    colorPicker.addEventListener("input", () => updateModelAppearance());
  }

  const opacitySlider = document.getElementById("opacity-slider");
  if (opacitySlider) {
    opacitySlider.addEventListener("input", (e) => {
      const display = document.getElementById("opacity-value");
      if (display) display.textContent = e.target.value + "%";
      updateModelAppearance();
    });
  }

  const bgColor = document.getElementById("bg-color");
  if (bgColor) {
    bgColor.addEventListener("input", (e) => {
      scene.background = new THREE.Color(e.target.value);
    });
  }

  // Камера
  const cameraPositions = {
    "cam-front": [0, 0, -3000],
    "cam-back": [0, 0, 600],
    "cam-left": [-600, 0, 0],
    "cam-right": [600, 0, 0],
    "cam-top": [0, 600, 0],
    "cam-bottom": [0, -600, 0],
    "cam-iso": [500, 400, 600],
    "cam-reset": [500, 400, 600],
  };

  for (const [id, pos] of Object.entries(cameraPositions)) {
    const btn = document.getElementById(id);
    if (btn) {
      btn.addEventListener("click", () => {
        camera.position.set(pos[0], pos[1], pos[2]);
        controls.target.set(0, 0, 0);
        controls.update();
      });
    }
  }

  // Сечение (упрощенно)
  const showPlaneBtn = document.getElementById("show-plane-btn");
  if (showPlaneBtn) {
    showPlaneBtn.addEventListener("click", () => {
      Logger.info("Функция сечения будет добавлена позже");
    });
  }

  // Скриншот
  const screenshotBtn = document.getElementById("screenshot-btn");
  if (screenshotBtn) {
    screenshotBtn.addEventListener("click", () => {
      renderer.render(scene, camera);
      const dataURL = renderer.domElement.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = dataURL;
      link.download = `gcode-screenshot-${Date.now()}.png`;
      link.click();
      Logger.info("Скриншот сохранен");
    });
  }

  // Лог
  const logClear = document.getElementById("log-clear");
  if (logClear) {
    logClear.addEventListener("click", () => Logger.clear());
  }

  // Сворачивание панели
  let panelVisible = true;
  const panel = document.getElementById("ui-panel");
  const toggleBtn = document.getElementById("toggle-panel");
  if (toggleBtn && panel) {
    toggleBtn.addEventListener("click", () => {
      panelVisible = !panelVisible;
      panel.style.display = panelVisible ? "block" : "none";
      toggleBtn.textContent = panelVisible ? "◀" : "▶";
      toggleBtn.style.left = panelVisible ? "340px" : "20px";
    });
  }
}

// ========== Настройка кликов для измерения ==========
function setupMeasurementClick() {
  const measureBtn = document.getElementById("measure-btn");
  const resetMeasureBtn = document.getElementById("reset-measure-btn");

  if (measureBtn) {
    measureBtn.addEventListener("click", () => {
      measuringMode = !measuringMode;
      measureBtn.textContent = measuringMode
        ? "🔍 Измерение активно"
        : "🔍 Измерить";
      document.getElementById("measure-result").innerHTML = measuringMode
        ? 'Расстояние: — <span style="color:#ff9800">(щелкните 2 точки)</span>'
        : "Расстояние: —";
      Logger.info(
        measuringMode
          ? "Режим измерения активирован"
          : "Режим измерения деактивирован",
      );
    });
  }

  if (resetMeasureBtn) {
    resetMeasureBtn.addEventListener("click", () => {
      measuringMode = false;
      measurePoints = [];
      measureObjects.forEach((obj) => scene.remove(obj));
      measureObjects = [];
      document.getElementById("measure-result").innerHTML = "Расстояние: —";
      if (measureBtn) measureBtn.textContent = "🔍 Измерить";
      Logger.info("Измерения сброшены");
    });
  }

  // Обработка кликов для измерения
  renderer.domElement.addEventListener("click", (event) => {
    if (!measuringMode || !currentModel) return;

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    mouse.x = (event.clientX / renderer.domElement.clientWidth) * 2 - 1;
    mouse.y = -(event.clientY / renderer.domElement.clientHeight) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(currentModel.children, true);

    if (intersects.length > 0) {
      const point = intersects[0].point;

      // Добавляем сферу в точку
      const geometry = new THREE.SphereGeometry(5, 8, 8);
      const material = new THREE.MeshStandardMaterial({ color: 0xff4444 });
      const sphere = new THREE.Mesh(geometry, material);
      sphere.position.copy(point);
      scene.add(sphere);
      measureObjects.push(sphere);

      measurePoints.push(point.clone());

      if (measurePoints.length === 2) {
        const dist = measurePoints[0].distanceTo(measurePoints[1]);
        document.getElementById("measure-result").innerHTML =
          `📏 Расстояние: ${dist.toFixed(2)} мм`;
        Logger.info(`Расстояние: ${dist.toFixed(2)} мм`);

        // Линия между точками
        const points = [measurePoints[0], measurePoints[1]];
        const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
        const lineMat = new THREE.LineBasicMaterial({ color: 0x44ff44 });
        const line = new THREE.Line(lineGeo, lineMat);
        scene.add(line);
        measureObjects.push(line);

        measuringMode = false;
        if (measureBtn) measureBtn.textContent = "🔍 Измерить";
      }
    }
  });
}

// ========== Анимация ==========
function animate() {
  requestAnimationFrame(animate);
  controls.update();

  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);

  frameCount++;
  const now = performance.now();
  if (now - lastTime >= 1000) {
    const fps = Math.round((frameCount * 1000) / (now - lastTime));
    if (statsElement) {
      statsElement.innerHTML = `⚡ ${fps} FPS | 📍 ${pointsCount.toLocaleString()} точек | 🔘 ${currentModel ? currentModel.children.length : 0} объектов`;
    }
    frameCount = 0;
    lastTime = now;
  }
}

function onWindowResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  labelRenderer.setSize(window.innerWidth, window.innerHeight);
}

// Запуск после полной загрузки страницы
window.addEventListener("load", () => {
  console.log("Страница полностью загружена, запуск приложения...");
  init();
});
