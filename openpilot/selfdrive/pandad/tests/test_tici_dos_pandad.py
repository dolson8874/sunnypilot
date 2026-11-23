from unittest.mock import MagicMock, patch

import pytest

from panda import McuType, Panda, PandaProtocolMismatch
from openpilot.selfdrive.pandad import pandad


SERIAL = "ABCDEF0123456789ABCDEF01"
SIGNATURE = b"panda-signature"


@pytest.fixture
def dos(monkeypatch):
  board = MagicMock()
  board.__enter__.return_value = board
  board.bootstub = False
  board.get_type.return_value = Panda.HW_TYPE_DOS
  board.get_signature.return_value = SIGNATURE
  board.get_packets_versions.return_value = (Panda.HEALTH_PACKET_VERSION, Panda.CAN_PACKET_VERSION)
  board.get_usb_serial.return_value = SERIAL
  board.health.return_value = {"heartbeat_lost": False}
  usb_list = MagicMock(return_value=[SERIAL])
  open_panda = MagicMock(return_value=board)
  open_panda.usb_list = usb_list
  open_panda.HW_TYPE_DOS = Panda.HW_TYPE_DOS
  open_panda.HEALTH_PACKET_VERSION = Panda.HEALTH_PACKET_VERSION
  open_panda.CAN_PACKET_VERSION = Panda.CAN_PACKET_VERSION
  monkeypatch.setattr(pandad, "Panda", open_panda)
  monkeypatch.setattr(pandad, "get_expected_signature", MagicMock(return_value=SIGNATURE))
  return board, open_panda


def test_dos_selects_internal_usb_and_f4_image(dos):
  board, open_panda = dos
  assert pandad.prepare_tici_panda() == SERIAL
  open_panda.usb_list.assert_called_once_with(usb_port=(1, (1, 2)))
  open_panda.assert_called_once_with(SERIAL, disable_checks=False, usb_port=(1, (1, 2)))
  pandad.get_expected_signature.assert_called_once_with(McuType.F4)
  board.flash.assert_not_called()


def test_dos_updates_legacy_firmware_with_f4_image(dos):
  board, _ = dos
  board.get_signature.side_effect = [b"legacy", SIGNATURE]
  assert pandad.prepare_tici_panda() == SERIAL
  board.flash.assert_called_once_with(fn=pandad.os.path.join(pandad.FW_PATH, McuType.F4.config.app_fn))


@pytest.mark.parametrize("failure", ["type", "signature", "protocol"])
def test_dos_refuses_incompatible_firmware(dos, failure):
  board, _ = dos
  if failure == "type":
    board.get_type.return_value = Panda.HW_TYPE_TRES
  elif failure == "signature":
    board.get_signature.return_value = b"legacy"
  else:
    board.get_packets_versions.return_value = (0, 0)
  with pytest.raises(PandaProtocolMismatch):
    pandad.prepare_tici_panda()
  if failure != "signature":
    board.flash.assert_not_called()


@pytest.mark.parametrize("mcu_type", [McuType.F4, McuType.H7])
def test_dos_recovers_only_f4_on_the_internal_port(dos, mcu_type):
  _, open_panda = dos
  open_panda.usb_list.return_value = []
  dfu_serial = "AABBCCDDEEFF"
  with patch.object(pandad, "PandaDFU") as dfu:
    dfu.usb_list.return_value = [dfu_serial]
    bootloader = dfu.return_value.__enter__.return_value
    bootloader.get_mcu_type.return_value = mcu_type
    if mcu_type == McuType.H7:
      with pytest.raises(PandaProtocolMismatch):
        pandad.prepare_tici_panda()
      bootloader.recover.assert_not_called()
    else:
      assert pandad.prepare_tici_panda() is None
      bootloader.recover.assert_called_once_with()
    dfu.usb_list.assert_called_once_with(usb_port=(1, (1, 2)))
    dfu.assert_called_once_with(dfu_serial, usb_port=(1, (1, 2)))
