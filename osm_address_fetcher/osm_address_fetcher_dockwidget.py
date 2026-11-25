# -*- coding: utf-8 -*-
"""Dock widget for the OSM Address Fetcher QGIS plugin."""

import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from qgis.PyQt import QtCore, QtWidgets, uic
from qgis.PyQt.QtCore import QUrl, QVariant, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsNetworkAccessManager,
    QgsPointXY,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "osm_address_fetcher_dockwidget_base.ui")
)


class OSMAddressFetcherDockWidget(QtWidgets.QDockWidget, FORM_CLASS):
    closingPlugin = pyqtSignal()

    OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.reply = None
        self.query_geometry_4326 = None
        self.selected_layer_id = None

        self.progressBar.setVisible(False)
        self.btnCancel.setEnabled(False)
        self.txtOutputPath.setEnabled(False)
        self.btnBrowse.setEnabled(False)

        self.btnBrowse.clicked.connect(self.browse_output)
        self.btnDownload.clicked.connect(self.start_download)
        self.btnCancel.clicked.connect(self.cancel_download)
        self.radTemporary.toggled.connect(self.update_output_controls)
        self.radGeoPackage.toggled.connect(self.update_output_controls)

        project = QgsProject.instance()
        project.layersAdded.connect(self.refresh_polygon_layers)
        project.layersRemoved.connect(self.refresh_polygon_layers)
        project.readProject.connect(self.refresh_polygon_layers)
        self.cboPolygonLayer.currentIndexChanged.connect(self.update_status)

        self.refresh_polygon_layers()
        self.update_output_controls()

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()

    def log(self, message, level=Qgis.Info):
        from qgis.core import QgsMessageLog
        QgsMessageLog.logMessage(message, "OSM Address Fetcher", level)

    def set_status(self, text):
        self.lblStatus.setText(text)
        self.log(text)

    def update_status(self):
        layer = self.current_polygon_layer()
        if layer is None:
            self.lblStatus.setText("Select a polygon layer to begin.")
        else:
            self.lblStatus.setText(f"Ready: {layer.name()}")

    def refresh_polygon_layers(self, *args):
        previous_id = self.cboPolygonLayer.currentData()
        self.cboPolygonLayer.blockSignals(True)
        self.cboPolygonLayer.clear()
        self.cboPolygonLayer.addItem("Select polygon layer...", None)

        layers = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
                continue
            layers.append(layer)

        for layer in sorted(layers, key=lambda item: item.name().lower()):
            self.cboPolygonLayer.addItem(layer.name(), layer.id())

        if previous_id:
            index = self.cboPolygonLayer.findData(previous_id)
            if index >= 0:
                self.cboPolygonLayer.setCurrentIndex(index)

        self.cboPolygonLayer.blockSignals(False)
        self.update_status()

    def current_polygon_layer(self):
        layer_id = self.cboPolygonLayer.currentData()
        if not layer_id:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        return layer if isinstance(layer, QgsVectorLayer) else None

    def update_output_controls(self):
        save_file = self.radGeoPackage.isChecked()
        self.txtOutputPath.setEnabled(save_file)
        self.btnBrowse.setEnabled(save_file)

    def browse_output(self):
        suggested = self.txtOutputPath.text().strip()
        if not suggested:
            project_path = QgsProject.instance().fileName()
            folder = os.path.dirname(project_path) if project_path else os.path.expanduser("~")
            suggested = os.path.join(folder, "OSM_Address_Data.gpkg")

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save address GeoPackage",
            suggested,
            "GeoPackage (*.gpkg)",
        )
        if path:
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"
            self.txtOutputPath.setText(path)

    def start_download(self):
        layer = self.current_polygon_layer()
        if layer is None:
            self.show_warning("Select a polygon layer.")
            return

        layer_name = self.txtLayerName.text().strip()
        if not layer_name:
            self.show_warning("Enter an output layer name.")
            return

        if self.radGeoPackage.isChecked() and not self.txtOutputPath.text().strip():
            self.show_warning("Choose an output GeoPackage file.")
            return

        if not self.chkAddressNodes.isChecked() and not self.chkBuildingAddresses.isChecked():
            self.show_warning("Enable address points, building addresses, or both.")
            return

        if self.radSelectedPolygon.isChecked():
            features = list(layer.selectedFeatures())
            if not features:
                self.show_warning("Select at least one polygon in the chosen layer.")
                return
        else:
            features = list(layer.getFeatures())
            if not features:
                self.show_warning("The chosen polygon layer contains no features.")
                return

        geometries = []
        for feature in features:
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            geometry = QgsGeometry(geometry)
            if not geometry.isGeosValid():
                geometry = geometry.makeValid()
            if geometry and not geometry.isEmpty():
                geometries.append(geometry)

        if not geometries:
            self.show_warning("No usable polygon geometry was found.")
            return

        merged = QgsGeometry.unaryUnion(geometries)
        if merged is None or merged.isEmpty():
            self.show_warning("The selected polygons could not be combined.")
            return

        transform = QgsCoordinateTransform(
            layer.crs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance(),
        )
        try:
            merged.transform(transform)
        except Exception as error:
            self.show_error(f"Coordinate transformation failed:\n{error}")
            return

        self.query_geometry_4326 = merged
        polygon_strings = self.geometry_to_overpass_polygons(merged)
        if not polygon_strings:
            self.show_warning("The selected geometry could not be converted to an Overpass polygon.")
            return

        query = self.build_query(polygon_strings)
        self.send_request(query)

    @staticmethod
    def geometry_to_overpass_polygons(geometry):
        polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
        output = []
        for polygon in polygons:
            if not polygon or not polygon[0]:
                continue
            ring = polygon[0]
            if len(ring) > 1500:
                step = max(1, len(ring) // 1200)
                ring = ring[::step]
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
            text = " ".join(f"{point.y():.7f} {point.x():.7f}" for point in ring)
            if text:
                output.append(text)
        return output

    def build_query(self, polygon_strings):
        clauses = []
        for polygon in polygon_strings:
            if self.chkAddressNodes.isChecked():
                clauses.append(f'node["addr:housenumber"](poly:"{polygon}");')
                clauses.append(f'node["addr:housename"](poly:"{polygon}");')
            if self.chkBuildingAddresses.isChecked():
                clauses.append(f'way["addr:housenumber"](poly:"{polygon}");')
                clauses.append(f'relation["addr:housenumber"](poly:"{polygon}");')
                clauses.append(f'way["addr:housename"](poly:"{polygon}");')
                clauses.append(f'relation["addr:housename"](poly:"{polygon}");')

        return "[out:json][timeout:120];\n(\n  " + "\n  ".join(clauses) + "\n);\nout center tags;"

    def send_request(self, query):
        payload = urlencode({"data": query}).encode("utf-8")
        request = QNetworkRequest(QUrl(self.OVERPASS_ENDPOINT))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/x-www-form-urlencoded")

        self.set_busy(True)
        self.progressBar.setRange(0, 0)
        self.set_status("Downloading addresses from OpenStreetMap...")

        self.reply = QgsNetworkAccessManager.instance().post(request, payload)
        self.reply.finished.connect(self.handle_response)

    def cancel_download(self):
        if self.reply is not None:
            self.reply.abort()
            self.reply.deleteLater()
            self.reply = None
        self.set_busy(False)
        self.set_status("Download cancelled.")

    def handle_response(self):
        reply = self.reply
        self.reply = None
        if reply is None:
            return

        if reply.error() != reply.NoError:
            message = reply.errorString()
            reply.deleteLater()
            self.set_busy(False)
            self.show_error(f"OpenStreetMap download failed:\n{message}")
            return

        raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
        reply.deleteLater()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self.set_busy(False)
            self.show_error("The Overpass server returned an invalid response.")
            return

        try:
            output_layer, count = self.create_address_layer(data)
            if count == 0:
                self.set_busy(False)
                self.show_warning("No OpenStreetMap addresses were found inside the selected polygon.")
                return

            if self.radGeoPackage.isChecked():
                output_layer = self.save_to_geopackage(output_layer)
                if output_layer is None:
                    self.set_busy(False)
                    return

            QgsProject.instance().addMapLayer(output_layer)
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(100)
            self.set_busy(False, keep_progress=True)
            self.set_status(f"Completed: {count} address point(s) created.")
            self.iface.mapCanvas().setExtent(output_layer.extent())
            self.iface.mapCanvas().refresh()
        except Exception as error:
            self.set_busy(False)
            self.log(str(error), Qgis.Critical)
            self.show_error(f"Address processing failed:\n{error}")

    def create_address_layer(self, data):
        layer_name = self.txtLayerName.text().strip() or "OSM_Addresses"
        output = QgsVectorLayer("Point?crs=EPSG:4326", layer_name, "memory")
        provider = output.dataProvider()

        field_defs = [
            ("Address_ID", QVariant.String),
            ("House_Number", QVariant.String),
            ("House_Name", QVariant.String),
            ("Unit", QVariant.String),
            ("Street", QVariant.String),
            ("Place", QVariant.String),
            ("Suburb", QVariant.String),
            ("City", QVariant.String),
            ("District", QVariant.String),
            ("State", QVariant.String),
            ("Postcode", QVariant.String),
            ("Full_Address", QVariant.String),
            ("Building_Type", QVariant.String),
            ("Address_Status", QVariant.String),
            ("Latitude", QVariant.Double),
            ("Longitude", QVariant.Double),
            ("Source", QVariant.String),
            ("OSM_ID", QVariant.String),
            ("OSM_Type", QVariant.String),
            ("Downloaded_On", QVariant.String),
        ]
        provider.addAttributes([QgsField(name, field_type) for name, field_type in field_defs])
        output.updateFields()

        seen_osm = set()
        seen_address = set()
        features = []
        downloaded_on = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        for element in data.get("elements", []):
            osm_type = str(element.get("type", ""))
            osm_id = str(element.get("id", ""))
            osm_key = f"{osm_type}:{osm_id}"
            if self.chkRemoveDuplicates.isChecked() and osm_key in seen_osm:
                continue

            longitude = element.get("lon")
            latitude = element.get("lat")
            if longitude is None or latitude is None:
                center = element.get("center") or {}
                longitude = center.get("lon")
                latitude = center.get("lat")
            if longitude is None or latitude is None:
                continue

            point = QgsGeometry.fromPointXY(QgsPointXY(float(longitude), float(latitude)))
            if self.query_geometry_4326 and not self.query_geometry_4326.intersects(point):
                continue

            tags = element.get("tags") or {}
            house_number = tags.get("addr:housenumber", "")
            house_name = tags.get("addr:housename", "")
            unit = tags.get("addr:unit", "")
            street = tags.get("addr:street", "")
            place = tags.get("addr:place", "")
            suburb = tags.get("addr:suburb", "")
            city = tags.get("addr:city", "")
            district = tags.get("addr:district", "")
            state = tags.get("addr:state", "")
            postcode = tags.get("addr:postcode", "")
            building_type = tags.get("building", "")

            full_address_parts = [
                house_number, house_name, unit, street, place,
                suburb, city, district, state, postcode,
            ]
            full_address = ", ".join(str(value).strip() for value in full_address_parts if str(value).strip())
            if not self.chkFullAddress.isChecked():
                full_address = ""

            normalized = "|".join(
                str(value).strip().lower() for value in (house_number, unit, street, place, postcode)
            )
            if self.chkRemoveDuplicates.isChecked() and normalized.strip("|"):
                if normalized in seen_address:
                    continue
                seen_address.add(normalized)

            meaningful_count = sum(bool(str(value).strip()) for value in (house_number, house_name, street, place, city, postcode))
            if house_number and street and (city or place):
                status = "Complete"
            elif meaningful_count >= 2:
                status = "Partial"
            elif house_number:
                status = "House number only"
            else:
                status = "Building address"

            feature = QgsFeature(output.fields())
            feature.setGeometry(point)
            feature.setAttributes([
                f"ADDR-{len(features) + 1:06d}",
                house_number,
                house_name,
                unit,
                street,
                place,
                suburb,
                city,
                district,
                state,
                postcode,
                full_address,
                building_type,
                status,
                float(latitude),
                float(longitude),
                "OpenStreetMap",
                osm_id,
                osm_type,
                downloaded_on,
            ])
            features.append(feature)
            seen_osm.add(osm_key)

        provider.addFeatures(features)
        output.updateExtents()
        return output, len(features)

    def save_to_geopackage(self, memory_layer):
        path = self.txtOutputPath.text().strip()
        layer_name = self.txtLayerName.text().strip() or "OSM_Addresses"

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"
        options.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteLayer
            if os.path.exists(path)
            else QgsVectorFileWriter.CreateOrOverwriteFile
        )

        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            memory_layer,
            path,
            QgsProject.instance().transformContext(),
            options,
        )
        if result[0] != QgsVectorFileWriter.NoError:
            self.show_error(f"Could not save the GeoPackage:\n{result[1]}")
            return None

        saved = QgsVectorLayer(f"{path}|layername={layer_name}", layer_name, "ogr")
        if not saved.isValid():
            self.show_error("The GeoPackage was written, but QGIS could not open the saved layer.")
            return None
        return saved

    def set_busy(self, busy, keep_progress=False):
        self.btnDownload.setEnabled(not busy)
        self.btnCancel.setEnabled(busy)
        self.cboPolygonLayer.setEnabled(not busy)
        self.grpOptions.setEnabled(not busy)
        self.grpOutput.setEnabled(not busy)

        if busy:
            self.progressBar.setVisible(True)
        elif keep_progress:
            self.progressBar.setVisible(True)
        else:
            self.progressBar.setVisible(False)
            self.progressBar.setRange(0, 100)
            self.progressBar.setValue(0)

    def show_warning(self, message):
        self.set_status(message)
        QtWidgets.QMessageBox.warning(self, "OSM Address Fetcher", message)

    def show_error(self, message):
        self.set_status(message)
        QtWidgets.QMessageBox.critical(self, "OSM Address Fetcher", message)
