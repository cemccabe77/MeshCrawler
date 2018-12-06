"""
This library will try to provide mesh conversion to and from every DCC and file format
we use here at Blur

The Mesh object itself will try to provide an efficient way to run algorithms on
3d mesh data

There are also convenience classes that act as function sets for mesh object components
Verts and Faces are the most common convenience classes and give access to adjacency
data (for backwards compatibility)

VertSet and FaceSet classes are just sets that also contain references back to the mesh
"""

class Mesh(object):
	"""
		The inputs to this mesh object are inspired by the .obj file format

		Arguments:
			verts: list of 3d vectors ((x,y,z), ...)
			faces: list of lists of vertex indices formatted like:
				[[1, 2, 3], [4, 5, 6, 7] ...]
			uvs (default:None): list of 2d vectors ((u, v), ...)
			uvFaces (default:none): face representations used for UVs
			uvMap (defaul:None): dict of lists of 2d vectors {channelName:((u, v), ...), ...}
			uvFaceMap (default:none): dict of face representations used for UVs
			ensureWinding (default:True): Ensure that neighbor operations return items in order

		Faces are ccw wound

		The idea for this data structure is to keep all the data in one place and have the
		individual convenience objects reference back to it. Storing in one place means I
		can store it efficiently, and allow for efficient editing and querying. The
		convenience layer on top means you can get "good enough" performance for high-level
		tasks without having to directly manipulate the underlying data.

		This will error out with non-manifold geometry. This is a feature not a bug ;)

		The only strange property is "Edge Adjacency", and this borrows some data from
		the winged edge structure. Given two neighboring vertices, return the bordering
		faces. The first face contains the vertices wound backwards (clockwise),
		the second face contains the vertices wound forwards (counter clockwise)
		For instance, we could pass the vert indices (0, 1), and get back (10, 13) where
		faces[10].verts is (1, 0, 2) and faces[13].verts is (0, 1, 3).

		UV's have a default mapping as part of class. However, named UV sets are supported
		through the uvMap and uvFaceMap arguments. The default mapping is automatically
		given the name 'default'. Partial uv sets are not handled

		Float Data:
			vertArray			: array of 3d floats
			uvMap				: map of d[name] => array of 2d floats

		Face Data:
			faceVertArray		: 2d array of vertex indices per face
			uvFaceMap			: map of d[name] => 2d array of UV indices per face

		Vert Data:
			vertToFaces			: 2d array of face indices per vert
			vertNeighbors		: 2d array of vert indices per vert
			vertWindingPairs	: map of vertIdx => [(ccw Vert Pair), ...]

		Edge Adjacency:
			faceEdgeAdjacency	: map of d[(vert1, vert2)] => (order, reverse) face indices
									where `order` contains (vert1, vert2) in the winding order
									and `reverse` contains (vert2, vert1) in the winding order
	"""
	def __init__(self, verts, faces, uvs=None, uvFaces=None, uvMap=None, uvFaceMap=None, ensureWinding=False):
		self._verts = None
		self._faces = None
		self._uvs = {}
		self._uvFaces = {}
		self._wound = ensureWinding

		self.children = []
		# load the float data
		self.vertArray = verts
		self.uvMap = uvMap or {}
		if uvs is not None:
			self.uvMap['default'] = uvs

		# build the empty face data
		self.faceVertArray = faces
		self.uvFaceMap = uvFaceMap or {}
		if uvFaces:
			self.uvFaceMap['default'] = uvFaces

		vertToFaces = {}
		neighborDict = {}
		hedgeCCWDict = {}
		hedgeCWDict = {}
		self.vertWindingPairs = {}
		for f, face in enumerate(self.faceVertArray):
			for v, vert in enumerate(face):
				vertToFaces.setdefault(vert, []).append(f)
				self.vertWindingPairs.setdefault(face[v-1], []).append((face[v-2], face[v]))
				neighborDict.setdefault(face[v-1], []).append(face[v])
				neighborDict.setdefault(face[v-1], []).append(face[v-2])
				hedgeCCWDict[(face[v-1], face[v])] = f
				hedgeCWDict[(face[v], face[v-1])] = f

		vertCount = len(self.vertArray)
		if ensureWinding:
			self.vertNeighbors = [self._linkPairs(self.vertWindingPairs[i]) for i in xrange(vertCount)]
		else:
			self.vertNeighbors = [neighborDict[i] for i in xrange(vertCount)]

		self.faceEdgeAdjacency = {}
		for i in xrange(vertCount):
			for j in self.vertNeighbors[i]:
				pair = (i, j)
				ccw = hedgeCCWDict.get(pair, None)
				cw = hedgeCWDict.get(pair, None)
				self.faceEdgeAdjacency[pair] = (ccw, cw)

		if ensureWinding:
			self.vertToFaces = []
			for i in xrange(vertCount):
				wings = [self.faceEdgeAdjacency[(i, j)] for j in self.vertNeighbors[i]]
				wings = [i for i in wings if None not in i]
				self.vertToFaces.append(self._linkPairs(wings))
		else:
			self.vertToFaces = [vertToFaces[i] for i in xrange(vertCount)]

	def ensureWinding(self):
		""" Ensure the winding of the mesh after-the-fact """
		if self._wound:
			return
		self._wound = True
		self.vertNeighbors = [self._linkPairs(self.vertWindingPairs[i]) for i in xrange(self.vertCount())]

		self.vertToFaces = []
		for i in xrange(self.vertCount()):
			wings = [self.faceEdgeAdjacency[(i, j)] for j in self.vertNeighbors[i]]
			wings = [i for i in wings if None not in i]
			self.vertToFaces.append(self._linkPairs(wings))

	@classmethod
	def loadObj(cls, path, ensureWinding=True):
		""" Read a .obj file and produce a Mesh object

		Args:
			path: The path to the .obj formatted file

		Returns:
			A Mesh() object containing lists of linked
			vertices, edges, and faces

		Raises:
			IOError: If the file cannot be opened
		"""
		vertices = []
		faces = []
		uvs = []
		uvIdxs = []
		nIdxs = []

		with open(path, 'r') as inFile:
			lines = inFile.readlines()

		for line in lines:
			sp = line.split()
			if sp == []:
				pass
			elif sp[0] == "v":
				v = [float(i) for i in sp[1:4]]
				vertices.append(v)

			elif sp[0] == 'vt':
				uv = [float(i) for i in sp[1:3]]
				uvs.append(uv)

			elif sp[0] == "f":
				face = []
				for s in sp[1:]:
					vt = [int(i)-1 if i else None for i in s.split('/')]
					# Pad out the face vert/uv/normal triples
					face.append(vt + [None]*3)
				# Then cut them back to 3
				# Still doing this even though I'm ignoring normals
				face = [i[:3] for i in face]
				f, u, n = zip(*face)
				faces.append(f)
				if any(u):
					uvIdxs.extend(u)
				if any(n):
					nIdxs.extend(n)

		flatUVs = None
		if uvIdxs:
			flatUVs = [uvs[i] for i in uvIdxs]

		return cls(vertices, faces, flatUVs, ensureWinding)

	@classmethod
	def loadAbc(cls, path, meshName=None, ensureWinding=True):
		""" Read a .abc file and produce a Mesh object

		Args:
			path: The path to the .abc formatted file

		Returns:
			A Mesh() object containing lists of linked
			vertices, edges, and faces

		Raises:
			IOError: If the file cannot be opened
		"""
		from alembic.Abc import IArchive
		from alembic.AbcGeom import IPolyMesh
		from blur3d.lib.alembiclib import findAlembicObject

		iarch = IArchive(str(path)) # because alembic hates unicode
		mesh = findAlembicObject(iarch.getTop(), abcType=IPolyMesh, name=meshName)
		sch = mesh.getSchema()
		rawVerts = sch.getPositionsProperty().samples[0]
		rawFaces = sch.getFaceIndicesProperty().samples[0]
		rawCounts = sch.getFaceCountsProperty().samples[0]
		iuvs = sch.getUVsParam()

		faces = []
		faceCounter = 0
		for count in rawCounts:
			faces.append(list(rawFaces[faceCounter: faceCounter+count]))
			faceCounter += count

		uvs = None
		uvFaces = None
		if iuvs.valid():
			uvValue = iuvs.getValueProperty().getValue()
			uvs = zip(uvValue.x, uvValue.y)
			if iuvs.isIndexed():
				idxs = list(iuvs.getIndexProperty().getValue())
				uvFaces = []
				uvCounter = 0
				for count in rawCounts:
					uvFaces.append(list(idxs[uvCounter: uvCounter+count]))
					uvCounter += count

		verts = []
		for v in rawVerts:
			verts.append(list(v))

		return cls(verts, faces, ensureWinding=ensureWinding)

	@staticmethod
	def _linkPairs(pairs):
		"""
		Take a list of paired items, and order them so the
		second item of a pair matches the first of the next pair
		Then return the first item of each pair for each cycle.
		for instance, with two cycles:
			input:   [(1, 2), (11, 12), (3, 1), (10, 11), (2, 3), (12, 10)]
			reorder: [[(1, 2), (2, 3), (3, 1)], [(10, 11), (11, 12), (12, 10)]]
			output:  [1, 2, 3, 10, 11, 12]
		"""
		fwPairs = dict(pairs)
		out = []
		while fwPairs:
			linked = []
			# pick a random start from whatever's left
			nxt = next(fwPairs.iterkeys())
			while nxt is not None:
				# Follow the pairs around until I cant find more
				nnxt = fwPairs.pop(nxt, None)
				linked.append((nxt, nnxt))
				nxt = nnxt

			if fwPairs and linked[0][0] != linked[-1][0]:
				# if there's still some left and we didn't find a cycle
				# then search backwards
				bkPairs = {j: i for i, j in fwPairs.iteritems()}
				inv = []
				nxt = linked[0][0]
				while nxt is not None:
					# Follow the pairs around until I cant find more
					nnxt = bkPairs.pop(nxt, None)
					inv.append((nnxt, nxt))
					nxt = nnxt
				#reverse and remove the extra (idx, None) pair
				linked = inv[-2::-1] + linked
				# Rebuild what's left into a new dict for the next group
				fwPairs = {j: i for i, j in bkPairs.iteritems()}

			# Parse the final output
			fin = [i for i, _ in linked]
			if fin[0] == fin[-1]:
				# Get rid of the doubled values when finding cycles
				fin = fin[:-1]
			out.extend(fin)
		return out

	def adjacentFacesByEdge(self, faceIdx):
		""" Get all faces that share an edge with the given face
		Winding Guaranteed Counterclockwise

		Args:
			faceIdx (int): Face Index

		Returns:
			list: List of faces indices that share an edge with the input

		Raises:
			IndexError: The input is out of range
		"""
		verts = self.faceVertArray[faceIdx]
		out = []
		for i in xrange(verts):
			edge = (verts[i-1], verts[i])
			_, rev = self.faceEdgeAdjacency.get(edge, (None, None))
			out.append(rev)
		return out

	def adjacentFacesByVert(self, faceIdx):
		""" Get all faces that share a vert with the given face
		Winding Not Guaranteed

		Args:
			faceIdx (int): Face Index

		Returns:
			list: List of faces indices that share a vert with the input

		Raises:
			IndexError: The input is out of range
		"""
		out = set()
		verts = self.faceVertArray[faceIdx]
		for v in verts:
			out.update(self.vertToFaces[v])
		return list(out)

	def adjacentVertsByFace(self, vertIdx):
		""" Get all verts that share a face with the given vert
		Winding Not Guaranteed

		Args:
			vertIdx (int): Vertex Index

		Returns:
			list: List of vertex indices that share a face with the input

		Raises:
			IndexError: The input is out of range
		"""
		faces = self.vertToFaces[vertIdx]
		out = set()
		for f in faces:
			out.update(self.faceVertArray[f])
		return list(out)

	def adjacentVertsByEdge(self, vertIdx):
		""" Get all verts that share an edge with the given vert
		Winding Guaranteed Counterclockwise

		Args:
			vertIdx (int): Vertex Index

		Returns:
			list: List of vertex indices that share an edge with the input

		Raises:
			IndexError: The input is out of range
		"""
		return self.vertNeighbors[vertIdx]

	def vertCount(self):
		""" Returns: The number of vertices in this mesh """
		return len(self.vertArray)

	def faceCount(self):
		""" Returns: The number of faces in this mesh """
		return len(self.faceVertArray)

	def verts(self):
		""" Get all vertex convenience objects

		Returns:
			list: List of vertex objects
		"""
		if self._verts is None:
			self._verts = [Vert(self, i) for i in xrange(len(self.vertArray))]
		return self._verts

	def faces(self):
		""" Get all face convenience objects

		Returns:
			list: List of face objects
		"""
		if self._faces is None:
			self._faces = [Face(self, i) for i in xrange(len(self.faceVertArray))]
		return self._faces

	def vertSet(self):
		""" Get a vertex set containing the whole mesh

		Returns:
			VertSet: A vertex set containing the whole mesh
		"""
		ret = VertSet(self, [])
		ret.update(range(len(self.vertArray)))
		return ret

	def faceSet(self):
		""" Get a face set containing the whole mesh

		Returns:
			FaceSet: A face set containing the whole mesh
		"""
		ret = FaceSet(self, [])
		ret.update(range(len(self.faceVertArray)))
		return ret

	def uvs(self, channelName='default'):
		""" Get all UV convenience objects

		Returns:
			list: List of UV objects
		"""
		if channelName not in self._uvs:
			uvm = self.uvMap.get(channelName)
			if uvm is not None:
				self._uvs[channelName] = [UV(self, channelName, i) for i in uvm]
		return self._uvs.get(channelName)

	def uvFaces(self, channelName='default'):
		""" Get all UV convenience objects

		Returns:
			list: List of UV objects
		"""
		if channelName not in self._uvFaces:
			uvfm = self.uvFaceMap.get(channelName, [])
			if uvfm is not None:
				self._uvFaces[channelName] = [UVFace(self, channelName, i) for i in uvfm]
		return self._uvFaces.get(channelName)

	def isBorderVert(self, vertIdx):
		""" Check if the given vertex index is along a border

		Returns:
			Bool: Whether the given vertex index is along a border
		"""

		neighbors = self.vertNeighbors[vertIdx]
		for n in neighbors:
			if None in self.faceEdgeAdjacency[(vertIdx, n)]:
				return True
		return False

	def getBorderVerts(self):
		""" Get a vertex set of the border vertices

		Returns:
			VertSet: VertSet of border vertices
		"""
		out = VertSet(self)
		for edge, adj in self.faceEdgeAdjacency.iteritems():
			if None in adj:
				out.update(edge)
		return out

	def clearCache(self):
		""" Clear all cached convenience classes """
		self._verts = None
		self._faces = None
		self._uvs = {}
		self._uvFaces = {}
		self.children = []

#######################################################################################

class MeshComponent(object):
	""" Base class for all mesh components
	Handles keeping track of the mesh and index

	Arguments:
		mesh (Mesh): The mesh object that this is a component of
		index (int): The index of this component
	"""
	__slot__ = 'mesh', 'index'
	def __init__(self, mesh, index):
		self.mesh = mesh
		self.index = index
		self.mesh.children.append(self)

	def __int__(self):
		return self.index

	def clear(self):
		""" Remove all reference data from this object """
		self.mesh = None
		self.mesh.children.remove(self)

	def __eq__(self, other):
		if isinstance(other, type(self)):
			if self.mesh is other.mesh:
				return self.index == other.index
			# Not worrying about floating point equality
			return self.value() == other.value()
		return NotImplemented

	def __hash__(self):
		return self.index


class Vert(MeshComponent):
	''' A convenience class for accessing and manipulating vertices '''
	def adjacentVertsByEdge(self):
		""" Get all verts that share an edge with the given vert

		Returns:
			list: List of verts that share an edge with the input
		"""
		idxs = self.mesh.adjacentVertsByEdge(self.index)
		verts = self.mesh.verts()
		return [verts[i] for i in idxs]

	def adjacentVertsByFace(self):
		""" Get all verts that share a face with the given vert

		Returns:
			list: List of verts that share a face with the input
		"""
		idxs = self.mesh.adjacentVertsByFace(self.index)
		verts = self.mesh.verts()
		return [verts[i] for i in idxs]

	def adjacentFaces(self):
		""" Get all faces that use this vertex

		Returns:
			list: List of faces that use this vertex
		"""
		idxs = self.mesh.vertToFaces[self.index]
		faces = self.mesh.faces()
		return [faces[i] for i in idxs]

	def value(self):
		""" Get the vertex's position

		Returns:
			tuple: (x, y, z) vertex position
		"""
		return self.mesh.vertArray[self.index]

	def setValue(self, pos):
		""" Set the vertex position

		Args:
			pos (tuple): (x, y, z) vertex position
		"""
		t = tuple(pos)
		assert len(t) == 3
		self.mesh.vertArray[self.index] = t


class Face(MeshComponent):
	''' A convenience class for accessing and manipulating faces '''
	def adjacentFacesByEdge(self):
		""" Get all faces that share an edge with the given face

		Returns:
			list: List of faces that share an edge with the input
		"""
		idxs = self.mesh.adjacentFacesByEdge(self.index)
		faces = self.mesh.faces()
		return [faces[i] for i in idxs]

	def adjacentFacesByVert(self):
		""" Get all faces that share a vert with the given face

		Returns:
			list: List of faces that share a vert with the input
		"""
		idxs = self.mesh.adjacentFacesByVert(self.index)
		faces = self.mesh.faces()
		return [faces[i] for i in idxs]

	def __eq__(self, other):
		if isinstance(other, Face):
			return set(self.verts()) == set(other.verts())
		return NotImplemented

	def __hash__(self):
		return hash(self.verts())

	def verts(self):
		""" Get all verts that make up this face

		Returns:
			list: List of vertexes that make up this face
		"""
		idxs = self.mesh.faceVertArray[self.index]
		verts = self.mesh.verts()
		return [verts[i] for i in idxs]

	def uvs(self, name='default'):
		""" Get all uvs that make up this face

		Returns:
			list: List of uvs that make up this face
		"""
		idxs = self.mesh.faceUVArray[name][self.index]
		uvs = self.mesh.uvs(name)
		return [uvs[i] for i in idxs]


class UV(MeshComponent):
	''' A convenience class for accessing and manipulating uvs '''
	__slot__ = 'mesh', 'index', 'name'
	def __init__(self, mesh, name, index):
		self.name = name
		super(UV, self).__init__(mesh, index)

	def value(self):
		""" Get the uv's position

		Returns:
			tuple: (u, v) position
		"""
		return self.mesh.uvMap[self.name][self.index]

	def setValue(self, pos):
		""" Set the uv's position

		Args:
			pos (tuple): (u, v) position
		"""
		t = tuple(pos)
		assert len(t) == 2
		self.mesh.uvMap[self.name][self.index] = t

	def __hash__(self):
		return hash(self.name, self.index)


class UVFace(MeshComponent):
	''' A convenience class for accessing and manipulating faces '''
	__slot__ = 'mesh', 'index', 'name'
	def __init__(self, mesh, name, index):
		self.name = name
		super(UVFace, self).__init__(mesh, index)

	def __eq__(self, other):
		if isinstance(other, UVFace):
			return set(self.uvs()) == set(other.uvs())
		return NotImplemented

	def __hash__(self):
		return hash(self.verts())

	def verts(self):
		""" Get all verts that make up this UVFace

		Returns:
			list: List of vertexes that make up this face
		"""
		idxs = self.mesh.faceVertArray[self.index]
		verts = self.mesh.verts()
		return [verts[i] for i in idxs]

	def uvs(self, name='default'):
		""" Get all uvs that make up this UVFace

		Returns:
			list: List of uvs that make up this face
		"""
		idxs = self.mesh.uvFaceMap[name][self.index]
		uvs = self.mesh.uvs(name)
		return [uvs[i] for i in idxs]

#######################################################################################

class MeshSetMeta(type):
	""" Wraps the magic methods to ensure that a reference to the mesh is kept """
	def __new__(mcs, clsName, bases, dct):
		names = ['__and__', '__or__', '__sub__', '__xor__', 'copy',
		'difference', 'intersection', 'union', 'symmetric_difference']

		rnames = ['__rand__', '__ror__', '__rsub__', '__rxor__']

		def wrap_closure(name, right):
			def inner(self, *args):
				result = getattr(set, name)(self, *args)
				if not hasattr(result, 'mesh'):
					if right:
						# Gotta special-case the __r*__ methods
						# because they get the mesh from the args
						result.mesh = args[0].mesh
					else:
						result.mesh = self.mesh
				return result
			inner.fn_name = name
			inner.__name__ = name
			return inner

		if set in bases:
			for attr in names:
				dct[attr] = wrap_closure(attr, False)
			for attr in rnames:
				dct[attr] = wrap_closure(attr, True)

		return super(MeshSetMeta, mcs).__new__(mcs, clsName, bases, dct)


class MeshSet(set):
	""" An set-like object that deals with geometry """
	__metaclass__ = MeshSetMeta
	def __init__(self, mesh, indices=None):
		idxs = [] if indices is None else [int(i) for i in indices]
		super(MeshSet, self).__init__(idxs)
		self.mesh = mesh
		self.mesh.children.append(self)

	def grow(self, growMethod, exclude=None, track=False):
		""" Add adjacent objects as determined by the growMethod, and
		keep track of the previous growth for optimization purposes

		Args:
			growMethod (function): A function that returns the neighbors
				for each object index
			exclude (MeshSet): A set of objects to exclude from growth
			track (bool): Whether to keep track of the exclude input as well

		Returns:
			MeshSet: An updated MeshSet
			MeshSet: (Only if track=True) The updated exclude set
		"""
		if not isinstance(exclude, type(self)):
			exclude = exclude or []
			exclude = type(self)(self.mesh, exclude)

		grown = type(self)(self.mesh)
		growSet = self - exclude

		for vert in growSet:
			grown.update(growMethod(vert))

		newGrown = grown - exclude
		if track:
			newExclude = exclude | growSet
			return newGrown, newExclude
		else:
			return newGrown

	def _partitionIslands(self, growMethod):
		''' Separate the current set into sets of neighboring objects

		Args:
			growMethod (function): A function that returns the neighbors
				for each object index

		Returns:
			list(MeshSet): A list of interconnected object sets
		'''
		myType = type(self)
		allVerts = myType(self.mesh, [])
		allVerts.update(self)
		islands = []

		while allVerts:
			seed = myType(self.mesh, [allVerts.pop()])
			island = myType(self.mesh, [])
			while seed:
				grown = myType(self.mesh, [])
				for vert in seed:
					grown.update(growMethod(vert))
				newIsland = (island | seed) & self
				seed = (grown - island) & self
				island = newIsland

			islands.append(island)
			allVerts.difference_update(island)
		return islands


class VertSet(MeshSet):
	""" A set-like object that deals with vertices """
	def growByEdge(self, exclude=None, track=False):
		""" Add verts that share edges with the current set
		Args:
			exclude (VertSet): A set of vertices to exclude from growth
			track (bool): Whether to keep track of the exclude input as well

		Returns:
			VertSet: An updated vertex set
		"""
		return self.grow(self.mesh.adjacentVertsByEdge, exclude=exclude, track=track)

	def growByFace(self, exclude=None, track=False):
		""" Add verts that share faces with the current set
		Args:
			exclude (VertSet): A set of vertices to exclude from growth
			track (bool): Whether to keep track of the exclude input as well

		Returns:
			VertSet: An updated vertex set
		"""
		return self.grow(self.mesh.adjacentVertsByFace, exclude=exclude, track=track)

	def partitionIslands(self):
		''' Separate the current set into sets of neighboring objects

		Returns:
			list(VertSet): A list of interconnected object sets
		'''
		return super(VertSet, self)._partitionIslands(self.mesh.adjacentVertsByFace)


class FaceSet(MeshSet):
	""" A set-like object that deals with faces """
	def growByEdge(self, exclude=None, track=False):
		""" Add faces that share edges with the current set
		Args:
			exclude (FaceSet): A set of faces to exclude from growth
			track (bool): Whether to keep track of the exclude input as well

		Returns:
			FaceSet: An updated face set
		"""
		return self.grow(self.mesh.adjacentFacesByEdge, exclude=exclude, track=track)

	def growByVert(self, exclude=None, track=False):
		""" Add faces that share verts with the current set
		Args:
			exclude (FaceSet): A set of faces to exclude from growth
			track (bool): Whether to keep track of the exclude input as well

		Returns:
			FaceSet: An updated face set
		"""
		return self.grow(self.mesh.adjacentFacesByVert, exclude=exclude, track=track)

	def partitionIslands(self):
		''' Separate the current set into sets of neighboring objects

		Returns:
			list(FaceSet): A list of interconnected object sets
		'''
		return super(FaceSet, self)._partitionIslands(self.mesh.adjacentFacesByVert)

