#import blurdev
#from blurdev.gui import Dialog, loadUi
import os, json
from MeshCrawler.Qt import QtCompat
from MeshCrawler.Qt.QtCore import Qt
from MeshCrawler.Qt.QtWidgets import (QApplication, QProgressDialog, QMessageBox, QFileDialog,
						  QTableWidgetSelectionRange, QTableWidgetItem, QDialog, QWidget)

from MeshCrawler.meshcrawlerErrors import TopologyMismatch, IslandMismatch
from MeshCrawler.meshcrawlerLib import matchByTopology
from MeshCrawler.meshcrawlerGen import matchGenerator, autoCrawlMeshes, partitionIslands, starMatchGenerator

from MeshCrawler.commands import (getVerts, getFaces, getUVs, selectVerts, getSingleSelection, getObjectName,
	getObjectByName, cloneObject, freezeObject, setObjectName, setAllVerts, getVertSelection, createRawObject,
	selectAdjacentEdges)

from MeshCrawler.mesh import Mesh
from MeshCrawler.unSubdivide import unSubdivide, getCenters

def getUiFile(fileVar, subFolder="ui", uiName=None):
	"""Get the path to the .ui file"""
	uiFolder, filename = os.path.split(fileVar)
	if uiName is None:
		uiName = os.path.splitext(filename)[0]
	if subFolder:
		uiFile = os.path.join(uiFolder, subFolder, uiName+".ui")
	return uiFile

class MatchTopologyWidget(QWidget):
	def __init__(self, parent=None):
		super(MatchTopologyWidget, self).__init__(parent)
		uiPath = getUiFile(__file__, uiName='MatchTopologyWidget')
		QtCompat.loadUi(uiPath, self)

		self.lastMatch = None
		self.uiExportBTN.hide()

		self.uiGetOrderBTN.clicked.connect(self.getOrder)
		self.uiGetShapeBTN.clicked.connect(self.getShape)
		self.uiExportBTN.clicked.connect(self.exportLast)

		self.uiPairUpBTN.clicked.connect(self.moveUp)
		self.uiPairDownBTN.clicked.connect(self.moveDown)

		self.uiPairAddBTN.clicked.connect(self.addPair)
		self.uiPairDeleteBTN.clicked.connect(self.deletePair)

		self.uiCrawlBTN.clicked.connect(self.crawl)
		self.uiGuessBTN.clicked.connect(self.guess)
		self.uiGuessNextBTN.clicked.connect(self.guessNext)
		self._matchGen = None
		self.uiGuessNextBTN.hide()

		self.uiGetVertBTN.clicked.connect(self.getVert)
		self.uiPairTABLE.itemSelectionChanged.connect(self.selectionChanged)

		self._maxHeight = self.uiAdvancedGRP.maximumHeight()
		self.uiAdvancedGRP.toggled.connect(self.displayAdvanced)
		self.uiAdvancedGRP.setChecked(False)

		#self.uiOrderLINE.setText('Order')
		#self.uiShapeLINE.setText('Shape')
		#self.uiOutputLINE.setText('asdf')

		self._orderMesh = None
		self._shapeMesh = None

	def displayAdvanced(self, shown):
		self.uiAdvancedWID.setVisible(shown)
		if not shown:
			self.uiAdvancedGRP.setFlat(True)
			self.uiAdvancedGRP.setMaximumHeight(15)

		else:
			self.uiAdvancedGRP.setFlat(False)
			self.uiAdvancedGRP.setMaximumHeight(self._maxHeight)

	def getOrder(self):
		sel = getSingleSelection()
		if not sel:
			return
		name = getObjectName(sel)
		self.uiOrderLINE.setText(name)
		self._orderMesh = None

	def getShape(self):
		sel = getSingleSelection()
		if not sel:
			return
		name = getObjectName(sel)
		self.uiShapeLINE.setText(name)
		self._shapeMesh = None

	def exportLast(self):
		if self.lastMatch is None:
			return
		d = QFileDialog(self, "Save Last Selection", "", "JSON (*.json);;All Files (*.*)")
		d.setAcceptMode(QFileDialog.AcceptSave)
		d.setDefaultSuffix('json')
		d.exec_()
		if d.result():
			path = d.selectedFiles()[0]
			with open(path, 'w') as f:
				json.dump(self.lastMatch, f)

	def addPair(self):
		rc = self.uiPairTABLE.rowCount()
		self.uiPairTABLE.insertRow(rc)

		orderObj = QTableWidgetItem()
		shapeObj = QTableWidgetItem()

		self.uiPairTABLE.setItem(rc, 0, orderObj)
		self.uiPairTABLE.setItem(rc, 1, shapeObj)

	def deletePair(self):
		cur = self.uiPairTABLE.currentRow()
		if cur < 0:
			return
		self.uiPairTABLE.removeRow(cur)

	def moveUp(self):
		self._move(True)

	def moveDown(self):
		self._move(False)

	def _move(self, goUp):
		src = self.uiPairTABLE.currentRow()
		col = self.uiPairTABLE.currentColumn()

		if goUp and src == 0:
			return #cannot move an item at the top up
		if not goUp and src == self.uiPairTABLE.rowCount() - 1:
			return #cannot move an item at the bottom down
		dst = src - 1 if goUp else src + 1

		srcItem = self.uiPairTABLE.takeItem(src, col)
		dstItem = self.uiPairTABLE.takeItem(dst, col)

		self.uiPairTABLE.setItem(src, col, dstItem)
		self.uiPairTABLE.setItem(dst, col, srcItem)

		unSel = QTableWidgetSelectionRange(src, col, src, col)
		toSel = QTableWidgetSelectionRange(dst, col, dst, col)
		self.uiPairTABLE.setRangeSelected(unSel, False)
		self.uiPairTABLE.setRangeSelected(toSel, True)
		self.uiPairTABLE.setCurrentCell(dst, col)

	def _orderObject(self):
		name = self.uiOrderLINE.text()
		return getObjectByName(name)

	def _shapeObject(self):
		name = self.uiShapeLINE.text()
		return getObjectByName(name)

	def getVert(self):
		col = self.uiPairTABLE.currentColumn()
		thing = self._orderObject() if col == 0 else self._shapeObject()
		item = self.uiPairTABLE.currentItem()

		if getVerts is not None:
			val = getVerts(thing)
			if val is not None:
				item.setData(Qt.EditRole, val)

	def loadMeshes(self, step, pBar):
		oo = self._orderObject()
		so = self._shapeObject()
		if oo is None or so is None:
			QMessageBox.warning(self, "Get objects", "Must have order and shape loaded")

		if self._orderMesh is None:
			orderVerts = getVerts(oo)
			orderFaces = getFaces(oo)
			orderUVs, orderUVFaces = getUVs(oo)
			pBar.setLabelText("Loading Order")
			QApplication.processEvents()
			self._orderMesh = Mesh(orderVerts, orderFaces, uvs=orderUVs, uvFaces=orderUVFaces)
			pBar.setValue(pBar.value() + step)

		if self._shapeMesh is None:
			shapeVerts = getVerts(so)
			shapeFaces = getFaces(so)
			shapeUVs, shapeUVFaces = getUVs(so)
			pBar.setLabelText("Loading Shape")
			QApplication.processEvents()
			self._shapeMesh = Mesh(shapeVerts, shapeFaces, uvs=shapeUVs, uvFaces=shapeUVFaces)
			pBar.setValue(pBar.value() + step)

	def guess(self):
		oo = self._orderObject()
		so = self._shapeObject()
		if oo is None or so is None:
			QMessageBox.warning(self, "Get objects", "Must have order and shape loaded")
			return

		pBar = QProgressDialog(self)
		pBar.show()
		pBar.setValue(0)
		self.loadMeshes(33, pBar)

		pBar.setLabelText("Partitioning islands")
		QApplication.processEvents()
		self._matchGen = matchGenerator(self._orderMesh, self._shapeMesh, skipMismatchedIslands=True)
		self.uiGuessNextBTN.show()

		self.guessNext()
		pBar.close()

	def guessNext(self):
		try:
			sm = next(self._matchGen)
		except StopIteration:
			self._matchGen = None
			self.uiGuessNextBTN.hide()
			QMessageBox.warning(self, "No more guesses", "No more guesses")
			return

		for _ in range(self.uiPairTABLE.rowCount()):
			self.uiPairTABLE.removeRow(0)

		for i, pair in enumerate(sm):
			self.uiPairTABLE.insertRow(i)

			orderObj = QTableWidgetItem()
			shapeObj = QTableWidgetItem()

			self.uiPairTABLE.setItem(i, 0, orderObj)
			self.uiPairTABLE.setItem(i, 1, shapeObj)

			orderObj.setData(Qt.EditRole, pair[0])
			shapeObj.setData(Qt.EditRole, pair[1])

	def _getItemData(self, item):
		if item is None:
			return None
		data = item.data(Qt.EditRole)
		try:
			data = int(data)
		except (ValueError, TypeError):
			return None
		return data

	def getPairData(self):
		pairs = []
		for row in range(self.uiPairTABLE.rowCount()):
			pair = []
			for col in [0, 1]:
				item = self.uiPairTABLE.item(row, col)
				data = self._getItemData(item)
				if data is None:
					raise ValueError("All cells must be filled in")
				pair.append(data)
			pairs.append(tuple(pair))
		return pairs

	def selectionChanged(self):
		sel = self.uiPairTABLE.selectedItems()
		row = self.uiPairTABLE.currentRow()
		col = self.uiPairTABLE.currentColumn()

		if len(sel) > 1:
			maxRow = self.uiPairTABLE.rowCount() - 1
			maxCol = self.uiPairTABLE.columnCount() - 1

			unSel = QTableWidgetSelectionRange(0, 0, maxRow, maxCol)
			toSel = QTableWidgetSelectionRange(row, col, row, col)
			self.uiPairTABLE.setRangeSelected(unSel, False)
			self.uiPairTABLE.setRangeSelected(toSel, True)

		if self.uiSelectVertsCHK.isChecked():
			curItem = self.uiPairTABLE.currentItem()
			if curItem.isSelected():
				data = self._getItemData(curItem)
			else:
				data = None

			obj = self._orderObject() if col == 0 else self._shapeObject()
			if selectVerts is not None:
				selectVerts(obj, data)

	def _crawlAdvanced(self, pairs, orderMesh, shapeMesh, pBar):
		ois = [frozenset(i) for i in partitionIslands(orderMesh)]
		sis = [frozenset(i) for i in partitionIslands(shapeMesh)]
		oVals, sVals = list(zip(*pairs))
		oCheck, sCheck = {}, {}
		oOnes, sOnes = [], []
		orderObj = self.uiOrderLINE.text()
		shapeObj = self.uiShapeLINE.text()

		for isles, vals, check in ((ois, oVals, oCheck), (sis, sVals, sCheck)):
			for i in isles:
				for v in vals:
					if v in i:
						check.setdefault(i, []).append(v)

		for check, obj, ones in ((oCheck, orderObj, oOnes), (sCheck, shapeObj, sOnes)):
			for val in check.values():
				if len(val) not in [1, 3]:
					QMessageBox.warning(self, "Selection error",
						"Must have exactly 1 or 3 verts on an island. Found on {0} {1}: {2}".format(
							obj, len(val), val))
					raise TopologyMismatch()
				elif len(val) == 1:
					ones.append(val[0])

		vertNum = len(orderMesh.vertArray)
		if not oOnes and not sOnes:
			matches = [matchByTopology(orderMesh, shapeMesh, pairs, vertNum=vertNum, pBar=pBar)]
		else:
			matches = []
			pairs = [tuple(i) for i in pairs]
			buildPairs = []
			for overts in oCheck.itervalues():
				for sverts in sCheck.itervalues():
					zPairs = list(zip(overts, sverts))
					if all([p in pairs for p in zPairs]):
						buildPairs.append(zPairs)

			for zPairs in buildPairs:
				if len(zPairs) == 1:
					for starPairs in starMatchGenerator(orderMesh, shapeMesh, zPairs[0][0], zPairs[0][1]):
						try:
							match = matchByTopology(orderMesh, shapeMesh, starPairs, vertNum=vertNum, pBar=pBar)
							break
						except TopologyMismatch:
							pass
					else:
						raise TopologyMismatch("Mismatch found in single-vert pairing: {0}".format(zPairs[0]))
				else:
					match = matchByTopology(orderMesh, shapeMesh, zPairs, vertNum=vertNum, pBar=pBar)
				matches.append(match)
		return matches

	def crawl(self):
		pairs = None
		if self.uiAdvancedGRP.isChecked():
			try:
				pairs = self.getPairData()
			except ValueError:
				pass
			if not pairs:
				QMessageBox.warning(self, "Could not get Vert pairs", "All vert pairs must be fully defined")
				return

		pBar = QProgressDialog(self)
		pBar.show()
		pBar.setLabelText("Crawling")
		pBar.setValue(0)
		QApplication.setOverrideCursor(Qt.WaitCursor)
		QApplication.processEvents()

		self.loadMeshes(33, pBar)

		skipMismatchedIslands = False # someday figure out how to make this work

		match = None
		title = 'No Match Found'
		msg = 'No Match Found'

		QApplication.processEvents()
		try:
			if self.uiAdvancedGRP.isChecked():
				match = self._crawlAdvanced(pairs, self._orderMesh, self._shapeMesh, pBar)
			else:
				match = autoCrawlMeshes(self._orderMesh, self._shapeMesh,
					skipMismatchedIslands=skipMismatchedIslands, pBar=pBar)
		except TopologyMismatch as m:
			title = 'Topology Mismatch'
			msg = str(m) or title
		except IslandMismatch as m:
			title = 'Island Mismatch'
			msg = str(m) or title
		finally:
			QApplication.restoreOverrideCursor()

		if not match:
			pBar.close()
			QMessageBox.warning(self, title, msg)
			return

		pBar.setValue(0)
		pBar.setLabelText("Building output")
		allMatch = []
		for m in match:
			allMatch.extend(m)
		allMatch = sorted(allMatch)

		orderObj = self._orderObject()
		shapeObj = self._shapeObject()
		shapeVerts = getVerts(shapeObj)
		orderVerts = getVerts(orderObj)

		nn = str(self.uiOutputLINE.text())
		fixitObject = cloneObject(orderObj, nn)
		freezeObject(fixitObject)

		self.lastMatch = allMatch

		for oIdx, sIdx in allMatch:
			orderVerts[oIdx] = shapeVerts[sIdx]
		setAllVerts(fixitObject, orderVerts)

		self.uiExportBTN.show()
		pBar.close()


class UnSubdivideWidget(QWidget):
	def __init__(self, parent=None):
		super(UnSubdivideWidget, self).__init__(parent)
		uiPath = getUiFile(__file__, uiName='UnSubdivideWidget')
		QtCompat.loadUi(uiPath, self)

		self.uiGetUnsubObjBTN.clicked.connect(self.getObjectFromSelection)
		self.uiGetHintsBTN.clicked.connect(self.getVertsFromSelection)
		self.uiUnSubdivideBTN.clicked.connect(self.doUnsub)

	def getObjectFromSelection(self):
		obj = getSingleSelection()
		if not obj:
			return
		objName = getObjectName(obj)
		self.uiUnsubObjLINE.setText(objName)

	def getVertsFromSelection(self):
		obj = self._getObject()
		if obj is None:
			QMessageBox.warning(self, "Get objects", "Must have an object loaded first")
			return
		sel = getVertSelection(obj)
		val = ','.join(map(str, sel)) if sel else ''
		self.uiManualHintsLINE.setText(val)

	def _getObject(self):
		objName = str(self.uiUnsubObjLINE.text())
		if not objName:
			return None
		return getObjectByName(objName)

	def _getHints(self):
		hints = str(self.uiManualHintsLINE.text())
		if not hints:
			return None
		hints = hints.strip().split(',')
		hints = [int(i.strip()) for i in hints]
		return hints

	def doUnsub(self):
		obj = self._getObject()
		if obj is None:
			QMessageBox.warning(self, "Get objects", "Must have an object loaded first")
			return
		pBar = QProgressDialog(self)
		pBar.setLabelText("Unsubdividing")
		pBar.setValue(0)
		pBar.setMaximum(100)


		hints = self._getHints()
		verts = getVerts(obj)
		faces = getFaces(obj)
		uvs, uvFaces = getUVs(obj)
		if self.uiSelectEdgesRDO.isChecked():
			centers = getCenters(faces, pBar=pBar)
			selectAdjacentEdges(obj, centers)
		else:

			newName = getObjectName(obj)
			newName = newName + "_UNSUB"
			repositionVerts = self.uiUpdatePositionsRDO.isChecked()
			pinBorders = self.uiPinBordersCHK.isChecked()
			rFaces, rVerts, rUVFaces, rUVs = unSubdivide(faces, verts, uvFaces, uvs,
				hints=hints, repositionVerts=repositionVerts, pinBorders=pinBorders, pBar=pBar)
			createRawObject(newName, rFaces, rVerts, rUVFaces, rUVs)


class MeshCrawlerDialog(QDialog):
	def __init__(self, parent=None):
		super(MeshCrawlerDialog, self).__init__(parent)
		uiPath = getUiFile(__file__)
		QtCompat.loadUi(uiPath, self)

		self.uiTopologyWID = MatchTopologyWidget(self.uiTopologyParWID)
		topoLay = self.uiTopologyParWID.layout()
		topoLay.addWidget(self.uiTopologyWID)

		self.uiUnSubWID = UnSubdivideWidget(self.uiUnSubParWID)
		subLay = self.uiUnSubParWID.layout()
		subLay.addWidget(self.uiUnSubWID)

