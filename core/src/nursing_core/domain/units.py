"""Units as UCUM codes, the codes FHIR's vital-signs profile uses. The code never converts."""

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from nursing_core.domain import DomainModel


class Ucum(StrEnum):
    CEL = "Cel"
    DEG_F = "[degF]"
    KG = "kg"
    LB = "[lb_av]"
    ML = "mL"
    MM_HG = "mm[Hg]"
    PER_MIN = "/min"
    PERCENT = "%"


class Quantity(DomainModel):
    value: Decimal
    unit: Ucum


TEMPERATURE_UNITS = frozenset({Ucum.CEL, Ucum.DEG_F})
WEIGHT_UNITS = frozenset({Ucum.KG, Ucum.LB})
VOLUME_UNITS = frozenset({Ucum.ML})


class UnitDefaults(DomainModel):
    """The unit a number has when the nurse wrote none. A weight may have no default."""

    temperature: Ucum
    weight: Ucum | None
    volume: Ucum

    @model_validator(mode="after")
    def _each_unit_fits_its_measure(self) -> Self:
        if self.temperature not in TEMPERATURE_UNITS:
            raise ValueError("temperature must be Cel or [degF]")
        if self.weight is not None and self.weight not in WEIGHT_UNITS:
            raise ValueError("weight must be kg, [lb_av] or none")
        if self.volume not in VOLUME_UNITS:
            raise ValueError("volume must be mL")
        return self
