from amaranth import *
from amaranth.lib import enum, wiring
from amaranth.lib.wiring import In, Out, flipped
from amaranth.utils import exact_log2

from ..memory import MemoryMap


__all__ = [
    "BurstType",
    "RespType",
    "LockType",
    "Feature",
    "Signature",
    "Interface",
    "Decoder",
    "Arbiter",
]


class BurstType(enum.Enum):
    """AXI Burst Types"""
    FIXED = 0b00
    INCR  = 0b01
    WRAP  = 0b10


class RespType(enum.Enum):
    OKAY   = 0b00
    EXOKAY = 0b01
    SLVERR = 0b10
    DECERR = 0b11


class LockType(enum.Enum):
    NORMAL = 0b0
    EXCLUSIVE = 0b1


# TODO: Should we strict to spec compliant feature sets, ie !last => !lock, etc
# TODO: USER Signalling???
class Feature(enum.Enum):
    """Optional Wishbone interface signals."""
    LAST    = "last"
    BURST   = "burst"
    REGION  = "region"
    LOCK    = "lock"
    CACHE   = "cache"
    QOS     = "qos"
    ID      = "id"

AXI4 = frozenset((Feature.LAST,))
AXI4LITE = frozenset()

class Signature(wiring.Signature):
    """AXI4 interface signals.

    Parameters
    ----------
    addr_width : int
        Width of the address signal.
    data_width : ``8``, ``16``, ``32`` or ``64``
        Width of the data signals ("port size" in Wishbone terminology).
    id_width : Optional[int]
        Width of the id signals

    Interface attributes
    --------------------
    The correspondence between the Amaranth-SoC signals and the Wishbone signals changes depending
    on whether the interface acts as an initiator or a target.

    """

    def __init__(self, *, addr_width, data_width, id_width = None, features=frozenset()):
        if not isinstance(addr_width, int) or addr_width < 0:
            raise TypeError(
                f"Address width must be a non-negative integer, not {addr_width!r}"
            )
        # TODO: Strictly speaking I believe the minimum width is 32
        if data_width not in (8, 16, 32, 64, 128, 256, 512, 1024, 2048):
            raise ValueError(
                f"Data width must be one of 8, 16, 32, 64, 128, 256, 512, 1024, 2048, not {data_width!r}"
            )
        for feature in features:
            Feature(feature)  # raises ValueError if feature is invalid

        # TODO: Should I remove the feature and just gate on id_width?
        if id_width is not None and Feature.ID not in features:
            raise ValueError(
                f"If ID feature is not enabled, id_width must be None, not {id_width!r}"
            )
        if Feature.ID in features and (not isinstance(id_width, int) or id_width <= 0):
            raise TypeError(
                f"ID width must be an integer larger than zero if the ID feature is enabled, not {id_width!r}"
            )
        if Feature.LAST not in features and Feature.BURST in features:
            raise TypeError(
                "BURST feature implies LAST feature"
            )

        self._addr_width = addr_width
        self._data_width = data_width
        self._id_width = id_width
        self._features = frozenset(Feature(f) for f in features)

        members = {}

        address_write_members = {
            "awaddr": Out(self.addr_width),
            "awprot": Out(3),
            "awvalid": Out(1),
            "awready": In(1),
        }

        data_write_members = {
            "wdata": Out(self.data_width),
            "wstrb": Out(self.data_width // 8),
            "wlast": Out(1),
            "wvalid": Out(1),
            "wready": In(1),
        }

        resp_write_members = {
            "bresp": In(RespType),
            "bvalid": In(1),
            "bready": Out(1),
        }

        address_read_members = {
            "araddr": Out(self.addr_width),
            "arprot": Out(3),
            "arvalid": Out(1),
            "arready": In(1),
        }

        data_read_members = {
            "rdata": In(self.data_width),
            "rresp": In(RespType),
            "rlast": In(1),
            "rvalid": In(1),
            "rready": Out(1),
        }

        if Feature.LAST in self.features:
            data_write_members["wlast"] = Out(1)
            data_read_members["rlast"] = Out(1)
        if Feature.BURST in self.features:
            address_write_members.update(
                {
                    "awlen": Out(8),
                    "awsize": Out(3),
                    "awburst": Out(BurstType),
                }
            )
            address_read_members.update(
                {
                    "arlen": Out(8),
                    "arsize": Out(3),
                    "arburst": Out(BurstType),
                }
            )
        if Feature.REGION in self.features:
            address_write_members["awregion"] = Out(4)
            address_read_members["arredion"] = Out(4)
        if Feature.LOCK in self.features:
            address_write_members["awlock"] = Out(LockType)
            address_read_members["arlock"] = Out(LockType)
        if Feature.CACHE in self.features:
            address_write_members["awcache"] = Out(4)
            address_read_members["arcache"] = Out(4)
        if Feature.QOS in self.features:
            address_write_members["awqos"] = Out(4)
            address_read_members["arqos"] = Out(4)
        if Feature.ID in self.features:
            address_write_members["awid"] = Out(self.id_width)
            address_read_members["arid"] = Out(self.id_width)
            resp_write_members["bid"] = In(self.id_width)

        members.update(address_write_members)
        members.update(data_write_members)
        members.update(resp_write_members)
        members.update(address_read_members)
        members.update(data_read_members)

        super().__init__(members)

    @property
    def addr_width(self):
        return self._addr_width

    @property
    def data_width(self):
        return self._data_width

    @property
    def id_width(self):
        return self._id_width

    @property
    def granularity(self):
        return 8

    @property
    def features(self):
        return self._features

    def create(self, *, path=None, src_loc_at=0):
        """Create a compatible interface.

        See :meth:`wiring.Signature.create` for details.

        Returns
        -------
        An :class:`Interface` object using this signature.
        """
        return Interface(
            addr_width=self.addr_width,
            data_width=self.data_width,
            id_width=self.id_width,
            features=self.features,
            path=path,
            src_loc_at=1 + src_loc_at,
        )

    def __eq__(self, other):
        """Compare signatures.

        Two signatures are equal if they have the same address width, data width, granularity and
        features.
        """
        return (
            isinstance(other, Signature)
            and self.addr_width == other.addr_width
            and self.data_width == other.data_width
            and self.id_width == other.id_width
            and self.features == other.features
        )

    def __repr__(self):
        return f"axi.Signature({self.members!r})"


class Interface(wiring.PureInterface):
    """Wishbone bus interface.

    Note that the data width of the underlying memory map of the interface is equal to port
    granularity, not port size. If port granularity is less than port size, then the address width
    of the underlying memory map is extended to reflect that.

    Parameters
    ----------
    addr_width : :class:`int`
        Width of the address signal. See :class:`Signature`.
    data_width : :class:`int`
        Width of the data signals. See :class:`Signature`.
    granularity : :class:`int`
        Granularity of select signals. Optional. See :class:`Signature`.
    features : iter(:class:`Feature`)
        Describes additional signals of this interface. Optional. See :class:`Signature`.
    path : iter(:class:`str`)
        Path to this Wishbone interface. Optional. See :class:`wiring.PureInterface`.

    Attributes
    ----------
    memory_map: :class:`MemoryMap`
        Memory map of the bus. Optional.
    """

    def __init__(
        self,
        *,
        addr_width,
        data_width,
        id_width=None,
        features=frozenset(),
        path=None,
        src_loc_at=0,
    ):
        super().__init__(
            Signature(
                addr_width=addr_width,
                data_width=data_width,
                id_width=id_width,
                features=features,
            ),
            path=path,
            src_loc_at=1 + src_loc_at,
        )
        self._memory_map = None

    @property
    def addr_width(self):
        return self.signature.addr_width

    @property
    def data_width(self):
        return self.signature.data_width

    @property
    def granularity(self):
        return self.signature.granularity

    @property
    def id_width(self):
        return self.signature.id_width

    @property
    def features(self):
        return self.signature.features

    @property
    def memory_map(self):
        if self._memory_map is None:
            raise AttributeError(f"{self!r} does not have a memory map")
        return self._memory_map

    @memory_map.setter
    def memory_map(self, memory_map):
        if not isinstance(memory_map, MemoryMap):
            raise TypeError(
                f"Memory map must be an instance of MemoryMap, not {memory_map!r}"
            )
        if memory_map.data_width != self.granularity:
            raise ValueError(
                f"Memory map has data width {memory_map.data_width}, which is "
                f"not the same as bus interface granularity {self.granularity}"
            )
        granularity_bits = exact_log2(self.data_width // self.granularity)
        effective_addr_width = self.addr_width + granularity_bits
        if memory_map.addr_width != max(1, effective_addr_width):
            raise ValueError(
                f"Memory map has address width {memory_map.addr_width}, which is "
                f"not the same as the bus interface effective address width "
                f"{effective_addr_width} (= {self.addr_width} address bits + "
                f"{granularity_bits} granularity bits)"
            )
        self._memory_map = memory_map

    def __repr__(self):
        return f"axi.Interface({self.signature!r})"


class Decoder(wiring.Component):
    """Wishbone bus decoder.

    An address decoder for subordinate Wishbone buses.

    Parameters
    ----------
    addr_width : :class:`int`
        Address width. See :class:`Signature`.
    data_width : :class:`int`
        Data width. See :class:`Signature`.
    granularity : :class:`int`
        Granularity. See :class:`Signature`
    features : iter(:class:`Feature`)
        Optional signal set. See :class:`Signature`.
    alignment : int, power-of-2 exponent
        Window alignment. Optional. See :class:`..memory.MemoryMap`.

    Attributes
    ----------
    bus : :class:`Interface`
        Wishbone bus providing access to subordinate buses.
    """

    def __init__(
        self,
        *,
        addr_width,
        data_width,
        id_width=None,
        features=frozenset(),
        alignment=exact_log2(4096),
        name=None,
    ):
        super().__init__(
            {
                "bus": In(
                    Signature(
                        addr_width=addr_width,
                        data_width=data_width,
                        id_width=id_width,
                        features=features,
                    )
                )
            }
        )
        if Feature.BURST in self.bus.features and alignment < exact_log2(4096):
            raise ValueError(f"With bursts supported peripherals must be aligned on 4096 byte boundaries but got {1<<alignment!r}")
        self.bus.memory_map = MemoryMap(
            addr_width=max(1, addr_width + exact_log2(data_width // self.bus.granularity)),
            data_width=8,
            alignment=alignment,
        )
        self._subs = dict()

    def align_to(self, alignment):
        """Align the implicit address of the next window.

        See :meth:`MemoryMap.align_to` for details.
        """
        return self.bus.memory_map.align_to(alignment)

    def add(self, sub_bus, *, name=None, addr=None, sparse=False):
        """Add a window to a subordinate bus.

        The decoder can perform either sparse or dense address translation. If dense address
        translation is used (the default), the subordinate bus must have the same data width as
        the decoder; the window will be contiguous. If sparse address translation is used,
        the subordinate bus may have data width less than the data width of the decoder;
        the window may be discontiguous. In either case, the granularity of the subordinate bus
        must be equal to or less than the granularity of the decoder.

        See :meth:`MemoryMap.add_resource` for details.
        """
        if isinstance(sub_bus, wiring.FlippedInterface):
            sub_bus_unflipped = flipped(sub_bus)
        else:
            sub_bus_unflipped = sub_bus
        if not isinstance(sub_bus_unflipped, Interface):
            raise TypeError(
                f"Subordinate bus must be an instance of axi.Interface, not "
                f"{sub_bus_unflipped!r}"
            )
        # TODO: Check is redundant for to-spec axi buses
        if sub_bus.granularity > self.bus.granularity:
            raise ValueError(
                f"Subordinate bus has granularity {sub_bus.granularity}, which is "
                f"greater than the decoder granularity {self.bus.granularity}"
            )
        if not sparse:
            if sub_bus.data_width != self.bus.data_width:
                raise ValueError(
                    f"Subordinate bus has data width {sub_bus.data_width}, which is "
                    f"not the same as decoder data width {self.bus.data_width} "
                    f"(required for dense address translation)"
                )
        else:
            if sub_bus.granularity != sub_bus.data_width:
                raise ValueError(
                    f"Subordinate bus has data width {sub_bus.data_width}, which is "
                    f"not the same as its granularity {sub_bus.granularity} "
                    f"(required for sparse address translation)"
                )

        # TODO: Think about what these are, most (all?) optional signals have a specified default
        for opt_output in {}:
            if (
                hasattr(sub_bus, opt_output)
                and Feature(opt_output) not in self.bus.features
            ):
                raise ValueError(
                    f"Subordinate bus has optional output {opt_output!r}, but the "
                    f"decoder does not have a corresponding input"
                )

        self._subs[sub_bus.memory_map] = sub_bus
        return self.bus.memory_map.add_window(
            sub_bus.memory_map, name=name, addr=addr, sparse=sparse
        )

    def elaborate(self, platform):
        m = Module()

        bus_list = []
        for sub_map, sub_name, (
            sub_pat,
            sub_ratio,
        ) in self.bus.memory_map.window_patterns():
            sub_bus = self._subs[sub_map]
            bus_list.append((sub_map, sub_pat, sub_ratio))

            m.d.comb += [
                sub_bus.awaddr.eq(self.bus.awaddr << exact_log2(sub_ratio)),
                sub_bus.awprot.eq(self.bus.awprot),

                sub_bus.wdata.eq(self.bus.wdata),
                sub_bus.wstrb.eq(self.bus.wstrb),

                sub_bus.araddr.eq(self.bus.araddr << exact_log2(sub_ratio)),
                sub_bus.arprot.eq(self.bus.arprot),
            ]

            # TODO: Where the spec specified default is zeros should I drop the explicit set
            if Feature.LAST in sub_bus.features:
                if Feature.LAST in self.bus.features:
                    m.d.comb += sub_bus.wlast.eq(self.bus.wlast)
                else:
                    m.d.comb += sub_bus.wlast.eq(1)
            if Feature.BURST in sub_bus.features:
                if Feature.BURST in self.bus.features:
                    m.d.comb += [
                        sub_bus.awlen.eq(self.bus.awlen),
                        sub_bus.awsize.eq(self.bus.awsize),
                        sub_bus.awburst.eq(self.bus.awburst),

                        sub_bus.arlen.eq(self.bus.arlen),
                        sub_bus.arsize.eq(self.bus.arsize),
                        sub_bus.arburst.eq(self.bus.arburst)
                    ]
                else:
                    m.d.comb += [
                        sub_bus.awlen.eq(0),
                        sub_bus.awsize.eq(exact_log2(sub_bus.data_width)),
                        sub_bus.awburst.eq(BurstType.INCR),

                        sub_bus.arlen.eq(0),
                        sub_bus.arsize.eq(exact_log2(sub_bus.data_width)),
                        sub_bus.arburst.eq(BurstType.INCR)
                    ]
            if Feature.REGION in sub_bus.features:
                if Feature.REGION in self.bus.features:
                    m.d.comb += [
                        sub_bus.awregion.eq(self.bus.awregion),
                        sub_bus.arregion.eq(self.bus.arregion),
                    ]
                else:
                    m.d.comb += [
                        sub_bus.awregion.eq(0),
                        sub_bus.arregion.eq(0),
                    ]
            if Feature.LOCK in sub_bus.features:
                if Feature.LOCK in self.bus.features:
                    m.d.comb += [
                        sub_bus.awlock.eq(self.bus.awlock),
                        sub_bus.arlock.eq(self.bus.arlock),
                    ]
                else:
                    m.d.comb += [
                        sub_bus.awlock.eq(0),
                        sub_bus.arlock.eq(0),
                    ]
            if Feature.CACHE in sub_bus.features:
                if Feature.CACHE in self.bus.features:
                    m.d.comb += [
                        sub_bus.awcache.eq(self.bus.awcache),
                        sub_bus.arcache.eq(self.bus.arcache),
                    ]
                else:
                    m.d.comb += [
                        sub_bus.awcache.eq(0),
                        sub_bus.arcache.eq(0),
                    ]
            if Feature.QOS in sub_bus.features:
                if Feature.QOS in self.bus.features:
                    m.d.comb += [
                        sub_bus.arqos.eq(self.bus.arqos),
                        sub_bus.awqos.eq(self.bus.awqos),
                    ]
                else:
                    m.d.comb += [
                        sub_bus.arqos.eq(0),
                        sub_bus.awqos.eq(0),
                    ]
            if Feature.ID in sub_bus.features:
                if Feature.ID in self.bus.features:
                    m.d.comb += [
                        sub_bus.arid.eq(self.bus.arid),
                        sub_bus.awid.eq(self.bus.awid),
                        sub_bus.bid.eq(self.bus.bid),
                    ]
                else:
                    m.d.comb += [
                        sub_bus.arid.eq(0),
                        sub_bus.awid.eq(0),
                        sub_bus.bid.eq(0),
                    ]

        write_hot = Signal(len(bus_list))
        w_need_address, wna = Signal(), Signal()
        w_need_data, wnd = Signal(), Signal()
        w_need_resp, wnr = Signal(), Signal()


        read_hot = Signal(len(bus_list))
        r_need_address, rna = Signal(), Signal()
        r_need_data, rnd = Signal(), Signal()

        m.d.comb += [
            wna.eq(w_need_address),
            wnd.eq(w_need_data),
            wnr.eq(w_need_resp),

            rna.eq(r_need_address),
            rnd.eq(r_need_data),
        ]

        m.d.sync += Assert(sum([i for i in write_hot]) <= 1)
        m.d.sync += Assert(sum([i for i in read_hot]) <= 1)

        # TODO: This implementation does not support pipelined transactions
        # TODO: ID Reflection, or maybe don't and make an adapter required as it would complicate future pipelining
        granularity_bits = exact_log2(self.bus.data_width // self.bus.granularity)
        for i, (sub_map, sub_pat, sub_ratio) in enumerate(bus_list):
            sub_bus = self._subs[sub_map]
            with m.If(write_hot[i] | (~write_hot.any() & self.bus.awvalid & self.bus.awaddr.matches(sub_pat[:-granularity_bits if granularity_bits > 0 else None]))):
                with m.If(~write_hot.any()):
                    m.d.comb += [
                        wna.eq(1),
                        wnd.eq(1),
                        wnr.eq(1),
                    ]

                with m.If(wna):
                    m.d.comb += [
                        sub_bus.awvalid.eq(self.bus.awvalid),
                        self.bus.awready.eq(sub_bus.awready),
                        wna.eq(~(self.bus.awvalid & sub_bus.awready))
                    ]
                with m.If(wnd):
                    m.d.comb += [
                        sub_bus.wvalid.eq(self.bus.wvalid),
                        self.bus.wready.eq(sub_bus.wready),
                        wnd.eq(~(self.bus.wvalid & sub_bus.wready & (self.bus.wlast if Feature.LAST in self.bus.features else 1)))
                    ]
                with m.If(wnr):
                    m.d.comb += [
                        self.bus.bvalid.eq(sub_bus.bvalid),
                        self.bus.bresp.eq(sub_bus.bresp),
                        sub_bus.bready.eq(self.bus.bready),
                        wnr.eq(~(self.bus.bready & sub_bus.bvalid)),
                    ]

                m.d.sync += [
                    w_need_address.eq(wna),
                    w_need_data.eq(wnd),
                    w_need_resp.eq(wnr),
                ]

                with m.If(wna | wnd | wnr == 0):
                    m.d.sync += write_hot.eq(0)
                with m.Else():
                    m.d.sync += write_hot.eq(1 << i)

            with m.If(read_hot[i] | (~read_hot.any() & self.bus.arvalid & self.bus.araddr.matches(sub_pat[:-granularity_bits if granularity_bits > 0 else None]))):
                with m.If(~read_hot.any()):
                    m.d.comb += [
                        rna.eq(1),
                        rnd.eq(1)
                    ]

                with m.If(rna):
                    m.d.comb += [
                        sub_bus.arvalid.eq(self.bus.arvalid),
                        self.bus.arready.eq(sub_bus.arready),
                        rna.eq(~(self.bus.arvalid & sub_bus.arready))
                    ]
                with m.If(rnd):
                    m.d.comb += [
                        sub_bus.rready.eq(self.bus.rready),
                        self.bus.rresp.eq(sub_bus.rresp),
                        self.bus.rdata.eq(sub_bus.rdata),
                        self.bus.rvalid.eq(sub_bus.rvalid),
                        rnd.eq(~(self.bus.rready & sub_bus.rvalid & (sub_bus.rlast if Feature.LAST in self.bus.features else 1)))
                    ]
                    if Feature.LAST in self.bus.features:
                        m.d.comb += self.bus.rlast.eq(sub_bus.rlast)

                m.d.sync += [
                    r_need_address.eq(rna),
                    r_need_data.eq(rnd),
                ]

                with m.If(rna | rnd == 0):
                    m.d.sync += read_hot.eq(0)
                with m.Else():
                    m.d.sync += read_hot.eq(1 << i)

        return m


class Arbiter(wiring.Component):
    """Wishbone bus arbiter.

    A round-robin arbiter for initiators accessing a shared Wishbone bus.

    Parameters
    ----------
    addr_width : int
        Address width. See :class:`Signature`.
    data_width : int
        Data width. See :class:`Signature`.
    granularity : int
        Granularity. See :class:`Signature`
    features : iter(:class:`Feature`)
        Optional signal set. See :class:`Signature`.

    Attributes
    ----------
    bus : :class:`Interface`
        Shared Wishbone bus.
    """

    def __init__(
        self, *, addr_width, data_width, features=frozenset()
    ):
        super().__init__(
            {
                "bus": Out(
                    Signature(
                        addr_width=addr_width,
                        data_width=data_width,
                        features=features,
                    )
                )
            }
        )
        self._intrs = []

    def add(self, intr_bus):
        """Add an initiator bus to the arbiter.

        The initiator bus must have the same address width and data width as the arbiter. The
        granularity of the initiator bus must be greater than or equal to the granularity of
        the arbiter.
        """
        if not isinstance(intr_bus, Interface):
            raise TypeError(
                f"Initiator bus must be an instance of wishbone.Interface, not "
                f"{intr_bus!r}"
            )
        if intr_bus.addr_width != self.bus.addr_width:
            raise ValueError(
                f"Initiator bus has address width {intr_bus.addr_width}, which is "
                f"not the same as arbiter address width {self.bus.addr_width}"
            )
        if intr_bus.granularity < self.bus.granularity:
            raise ValueError(
                f"Initiator bus has granularity {intr_bus.granularity}, which is "
                f"lesser than the arbiter granularity {self.bus.granularity}"
            )
        if intr_bus.data_width != self.bus.data_width:
            raise ValueError(
                f"Initiator bus has data width {intr_bus.data_width}, which is not "
                f"the same as arbiter data width {self.bus.data_width}"
            )
        for opt_output in {"err", "rty"}:
            if hasattr(self.bus, opt_output) and not hasattr(intr_bus, opt_output):
                raise ValueError(
                    f"Arbiter has optional output {opt_output!r}, but the initiator "
                    f"bus does not have a corresponding input"
                )
        self._intrs.append(intr_bus)

    def elaborate(self, platform):
        m = Module()

        requests = Signal(len(self._intrs))
        grant = Signal(range(len(self._intrs)))
        m.d.comb += requests.eq(Cat(intr_bus.cyc for intr_bus in self._intrs))

        bus_busy = self.bus.cyc
        if hasattr(self.bus, "lock"):
            # If LOCK is not asserted, we also wait for STB to be deasserted before granting bus
            # ownership to the next initiator. If we didn't, the next bus owner could receive
            # an ACK (or ERR, RTY) from the previous transaction when targeting the same
            # peripheral.
            bus_busy &= self.bus.lock | self.bus.stb

        with m.If(~bus_busy):
            with m.Switch(grant):
                for i in range(len(requests)):
                    with m.Case(i):
                        for pred in reversed(range(i)):
                            with m.If(requests[pred]):
                                m.d.sync += grant.eq(pred)
                        for succ in reversed(range(i + 1, len(requests))):
                            with m.If(requests[succ]):
                                m.d.sync += grant.eq(succ)

        with m.Switch(grant):
            for i, intr_bus in enumerate(self._intrs):
                m.d.comb += intr_bus.dat_r.eq(self.bus.dat_r)
                if hasattr(intr_bus, "stall"):
                    intr_bus_stall = Signal(init=1)
                    m.d.comb += intr_bus.stall.eq(intr_bus_stall)

                with m.Case(i):
                    ratio = intr_bus.granularity // self.bus.granularity
                    m.d.comb += [
                        self.bus.adr.eq(intr_bus.adr),
                        self.bus.dat_w.eq(intr_bus.dat_w),
                        self.bus.sel.eq(
                            Cat(sel.replicate(ratio) for sel in intr_bus.sel)
                        ),
                        self.bus.we.eq(intr_bus.we),
                        self.bus.stb.eq(intr_bus.stb),
                    ]
                    m.d.comb += self.bus.cyc.eq(intr_bus.cyc)
                    if hasattr(self.bus, "lock"):
                        m.d.comb += self.bus.lock.eq(getattr(intr_bus, "lock", 0))
                    if hasattr(self.bus, "cti"):
                        m.d.comb += self.bus.cti.eq(
                            getattr(intr_bus, "cti", CycleType.CLASSIC)
                        )
                    if hasattr(self.bus, "bte"):
                        m.d.comb += self.bus.bte.eq(
                            getattr(intr_bus, "bte", BurstTypeExt.LINEAR)
                        )

                    m.d.comb += intr_bus.ack.eq(self.bus.ack)
                    if hasattr(intr_bus, "err"):
                        m.d.comb += intr_bus.err.eq(getattr(self.bus, "err", 0))
                    if hasattr(intr_bus, "rty"):
                        m.d.comb += intr_bus.rty.eq(getattr(self.bus, "rty", 0))
                    if hasattr(intr_bus, "stall"):
                        m.d.comb += intr_bus_stall.eq(
                            getattr(self.bus, "stall", ~self.bus.ack)
                        )

        return m
